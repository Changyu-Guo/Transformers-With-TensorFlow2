# -*- coding: utf - 8 -*-

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf

from layers.attention_layers.multi_head_attention_layer import MultiHeadAttention
from layers.attention_layers.einsum_dense import EinsumDense


class TransformerEncoderLayer(tf.keras.layers.Layer):
    def __init__(
            self,
            num_attention_heads,
            intermediate_size,
            intermediate_activation,
            hidden_dropout_rate=0.0,
            attention_dropout_rate=0.0,
            output_range=None,
            kernel_initializer='glorot_uniform',
            bias_initializer='zeros',
            kernel_regularizer=None,
            bias_regularizer=None,
            activity_regularizer=None,
            kernel_constraint=None,
            bias_constraint=None,
            use_bias=True,
            norm_first=False,
            norm_epsilon=1e-12,
            intermediate_dropout=0.0,
            **kwargs
    ):
        super(TransformerEncoderLayer, self).__init__(**kwargs)

        self._num_attention_heads = num_attention_heads
        self._intermediate_size = intermediate_size
        self._intermediate_activation = intermediate_activation
        self._hidden_dropout_rate = hidden_dropout_rate
        self._attention_dropout_rate = attention_dropout_rate
        self._output_range = output_range
        self._kernel_initializer = kernel_initializer
        self._bias_initializer = bias_initializer
        self._kernel_regularizer = kernel_regularizer
        self._bias_regularizer = bias_regularizer
        self._activity_regularizer = activity_regularizer
        self._kernel_constraint = kernel_constraint
        self._bias_constraint = bias_constraint
        self._use_bias = use_bias
        self._norm_first = norm_first
        self._norm_epsilon = norm_epsilon
        self._intermediate_dropout = intermediate_dropout

    def build(self, input_shape):
        """
        :param input_shape: 包含 inputs 和 mask 或仅包含 inputs
        其中 inputs 的 shape 应该为 (batch_size, seq_len, hidden_size)
        mask 的 shape 应该为 (batch_size, seq_len, seq_len)
        """

        # 获取 input 相关参数
        input_tensor_shape = input_shape[0] if len(input_shape) == 2 else input_shape
        input_tensor_shape = tf.TensorShape(input_tensor_shape)
        if len(input_tensor_shape) != 3:
            raise ValueError(
                'TransformerEncoderLayer expects a three-dim input of '
                'shape [batch_size, seq_len, hidden_size]'
            )
        batch_size, seq_len, hidden_size = input_tensor_shape

        # 获取 attention mask 相关参数
        if len(input_shape) == 2:
            mask_tensor_shape = tf.TensorShape(input_shape[1])
            expected_mask_tensor_shape = tf.TensorShape(
                [batch_size, seq_len, seq_len]
            )
            if not expected_mask_tensor_shape.is_compatible_with(mask_tensor_shape):
                raise ValueError(
                    'When passing a mask tensor to TransformerEncoderLayer, the '
                    'mask tensor must be of shape [batch_size, '
                    'seq_len, seq_len] (here %s). Got a '
                    'mask tensor of shape %s.' %
                    (expected_mask_tensor_shape, mask_tensor_shape)
                )

        # 对 size per head 进行计算
        if hidden_size % self._num_attention_heads != 0:
            raise ValueError(
                'The input size (%d) is not a multiple of the number of attention '
                'heads (%d)' % (hidden_size, self._num_attention_heads)
            )

        self._size_per_head = int(hidden_size // self._num_attention_heads)

        # 构建通用参数
        common_kwargs = dict(
            kernel_initializer=self._kernel_initializer,
            bias_initializer=self._bias_initializer,
            kernel_regularizer=self._kernel_regularizer,
            bias_regularizer=self._bias_regularizer,
            activity_regularizer=self._activity_regularizer,
            kernel_constraint=self._kernel_constraint,
            bias_constraint=self._bias_constraint
        )

        # attention layer
        self._attention_layer = MultiHeadAttention(
            num_attention_heads=self._num_attention_heads,
            size_per_head_for_query_and_key=self._size_per_head,
            attention_dropout_rate=self._attention_dropout_rate,
            use_bias=self._use_bias,
            name='self_attention',
            **common_kwargs
        )
        # attention 后接的 dropout
        # (任意 dense 操作之后都会接一个 dropout)
        self._attention_dropout = tf.keras.layers.Dropout(
            rate=self._hidden_dropout_rate
        )
        # attention 后接的 layer norm
        self._attention_layer_norm = tf.keras.layers.LayerNormalization(
            name='self_attention_layer_norm',
            axis=-1,
            epsilon=self._norm_epsilon,
            dtype=tf.float32
        )

        # 全连接神经网络
        self._intermediate_dense = EinsumDense(
            'abc,cd->abd',
            output_shape=(None, self._intermediate_size),
            bias_axes='d',
            name='feed_forward_net',
            **common_kwargs
        )

        policy = tf.keras.mixed_precision.experimental.global_policy()
        if policy.name == 'mixed_bfloat16':
            policy = tf.float32

        # 全连接神经网络的激活函数
        self._intermediate_dense_activation = tf.keras.layers.Activation(
            self._intermediate_activation, dtype=policy
        )
        self._intermediate_dropout_layer = tf.keras.layers.Dropout(
            rate=self._intermediate_dropout
        )

        # 输出
        # (全连接神经网络被拆分为了 filter_dense 和 output_dense)
        self._output_dense = EinsumDense(
            'abc,cd->abd',
            output_shape=(None, hidden_size),
            bias_axes='d',
            name='output_dense',
            **common_kwargs
        )
        self._output_dropout = tf.keras.layers.Dropout(
            rate=self._hidden_dropout_rate
        )
        self._output_layer_norm = tf.keras.layers.LayerNormalization(
            name='output_layer_norm',
            axis=-1,
            epsilon=self._norm_epsilon,
            dtype=tf.float32
        )
        super(TransformerEncoderLayer, self).build(input_shape)

    def call(self, inputs):
        # input: (batch_size, seq_len, hidden_size)
        # mask: (batch_size, seq_len, seq_len)
        if isinstance(inputs, (list, tuple)) and len(inputs) == 2:
            input_tensor, attention_mask = inputs
        else:
            input_tensor, attention_mask = (inputs, None)

        if self._output_range:
            target_tensor = input_tensor[:, 0: self._output_range, :]
            attention_mask = attention_mask[:, 0: self._output_range, :]
        else:
            if self._norm_first:
                source_tensor = input_tensor  # 保留操作前的数据，用于后面残差连接
                input_tensor = self._attention_layer_norm(input_tensor)
            target_tensor = input_tensor

        attention_output = self._attention_layer(
            query=target_tensor, value=input_tensor, attention_mask=attention_mask
        )
        attention_output = self._attention_dropout(attention_output)
        # 如果之前做过 layer norm，这里只需要进行残差连接
        if self._norm_first:
            attention_output = source_tensor + attention_output
        # 否则先残差连接，然后 layer norm
        else:
            attention_output = self._attention_layer_norm(
                target_tensor + attention_output
            )

        if self._norm_first:
            source_attention_output = attention_output
            attention_output = self._output_layer_norm(attention_output)

        feed_forward_net_output = self._intermediate_dense(attention_output)
        feed_forward_net_output = self._intermediate_dense_activation(feed_forward_net_output)

        layer_output = self._output_dense(feed_forward_net_output)
        layer_output = self._output_dropout(layer_output)

        layer_output = tf.cast(layer_output, tf.float32)
        if self._norm_first:
            layer_output = source_attention_output + layer_output
        else:
            layer_output = self._output_layer_norm(layer_output + attention_output)

        return layer_output

    def get_config(self):
        config = {
            'num_attention_heads': self._num_attention_heads,
            'intermedia_size': self._intermediate_size,
            'intermediate_activation': self._intermediate_activation,
            'hidden_dropout_rate': self._hidden_dropout_rate,
            'attention_dropout_rate': self._attention_dropout_rate,
            'output_range': self._output_range,
            'kernel_initializer': tf.keras.initializers.serialize(self._kernel_initializer),
            'bias_initializer': tf.keras.initializers.serialize(self._bias_initializer),
            'kernel_regularizer':
                tf.keras.regularizers.serialize(self._kernel_regularizer),
            'bias_regularizer':
                tf.keras.regularizers.serialize(self._bias_regularizer),
            'activity_regularizer':
                tf.keras.regularizers.serialize(self._activity_regularizer),
            'kernel_constraint':
                tf.keras.constraints.serialize(self._kernel_constraint),
            'bias_constraint':
                tf.keras.constraints.serialize(self._bias_constraint),
            'use_bias': self._use_bias,
            'norm_first': self._norm_first,
            'norm_epsilon': self._norm_epsilon,
            'intermediate_dropout': self._intermediate_dropout
        }
        base_config = super(TransformerEncoderLayer, self).get_config()
        return dict(list(base_config.items()) + list(config.items()))
