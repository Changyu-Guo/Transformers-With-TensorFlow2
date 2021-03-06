# -*- coding: utf - 8 -*-

import tensorflow as tf
from absl import logging
logging.set_verbosity(logging.INFO)


class Net(tf.keras.Model):

    def __init__(self):
        super(Net, self).__init__()
        self.dense = tf.keras.layers.Dense(units=5, kernel_initializer='glorot_uniform')

    def call(self, x):
        return self.dense(x)


def toy_dataset():
    # (10, 1)
    inputs = tf.range(10000000)[:, None]
    # (10, 5)
    labels = inputs * 5 + tf.range(5)[None, :]
    labels = tf.cast(labels, tf.float32)
    return tf.data.Dataset.from_tensor_slices(
        dict(x=inputs, y=labels)
    ).repeat().batch(2)


def train_one_step(model, example, optimizer):
    with tf.GradientTape() as tape:
        output = model(example['x'])
        print(example['x'])
        loss = tf.reduce_mean(tf.abs(output - example['y']))
    variables = model.trainable_variables
    grads = tape.gradient(loss, variables)
    optimizer.apply_gradients(zip(grads, variables))
    return loss


def train_and_checkpoint(net, optimizer, ckpt, dataset):
    if ckpt.restore(tf.train.latest_checkpoint('./tmp/')):
        logging.info('Load checkpoint {}'.format(tf.train.latest_checkpoint('./tmp/')))
    else:
        logging.info('No checkpoint to load')
    for _ in range(2):
        example = next(dataset)
        loss = train_one_step(net, example, optimizer)
        iterations = optimizer.iterations.numpy()
        if iterations % 1 == 0:
            ckpt.save('./tmp/tf_ckpts')
            print('Saved checkpoint for step {}'.format(iterations))
            print('loss {:1.2f}'.format(loss.numpy()))


def main():
    if not tf.io.gfile.exists('./tmp'):
        tf.io.gfile.makedirs('./tmp')
    net = Net()
    dataset = iter(toy_dataset())
    optimizer = tf.keras.optimizers.Adam(0.1)
    ckpt = tf.train.Checkpoint(
        net=net,
        optimizer=optimizer,
        dataset=dataset
    )
    train_and_checkpoint(net, optimizer, ckpt, dataset)


if __name__ == '__main__':
    main()
