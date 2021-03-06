# -*- coding: utf - 8 -*-

import tensorflow as tf


class WordEmbedding(tf.keras.layers.Layer):
    def __init__(
            self,
            vocab_size,
            embedding_size,
            initializer='glorot_uniform',
            use_one_hot=False,
            use_scale=False,
            **kwargs
    ):
        super(WordEmbedding, self).__init__(**kwargs)
        self._vocab_size = vocab_size
        self._embedding_size = embedding_size
        self._initializer = initializer
        self._use_one_hot = use_one_hot
        self._use_scale = use_scale

    def get_config(self):
        config = {
            'vocab_size': self._vocab_size,
            'embedding_size': self._embedding_size,
            'initializer': self._initializer,
            'use_one_hot': self._use_one_hot,
            'use_scale': self._use_scale
        }
        base_config = super(WordEmbedding, self).get_config()
        return dict(list(base_config.items()) + list(config.items()))

    def build(self, input_shape):
        self.embeddings = self.add_weight(
            'embeddings',
            shape=[self._vocab_size, self._embedding_size],
            initializer=self._initializer,
            dtype=tf.float32
        )
        super(WordEmbedding, self).build(input_shape)

    def call(self, inputs, mode='embedding'):
        if mode == 'embedding':
            return self._embedding(inputs)
        elif mode == 'linear':
            return self._linear(inputs)
        else:
            raise ValueError('mode {} is invalid'.format(mode))

    def _embedding(self, inputs):

        with tf.name_scope('embedding'):

            # 将 inputs 展平
            flat_inputs = tf.reshape(inputs, shape=(-1,))

            # 先将词转为 one-hot 再嵌入
            if self._use_one_hot:
                one_hot_data = tf.one_hot(
                    flat_inputs,
                    depth=self._vocab_size,
                    dtype=self.embeddings.dtype
                )
                embeddings = tf.matmul(one_hot_data, self.embeddings)

            # 直接使用词表中的向量
            else:
                embeddings = tf.gather(self.embeddings, flat_inputs)

            # (batch_size * seq_len,) -> (batch_size, seq_len, hidden_size)
            embeddings = tf.reshape(
                embeddings,
                tf.concat([tf.shape(inputs), [self._embedding_size]], axis=0)
            )

            # set shape
            embeddings.set_shape(inputs.shape.as_list() + [self._embedding_size])

            # scale
            if self._use_scale:
                embeddings *= self._embedding_size ** 0.5

            return embeddings

    def _linear(self, inputs):
        with tf.name_scope('pre_softmax_linear'):
            batch_size = tf.shape(inputs)[0]
            length = tf.shape(inputs)[1]

            x = tf.reshape(inputs, [-1, self._embedding_size])
            logits = tf.matmul(
                x, self.embeddings,
                transpose_b=True
            )

            return tf.reshape(logits, [batch_size, length, self._vocab_size])
