import argparse
import os
import numpy as np
import math

import torchvision.transforms as transforms
from torchvision.utils import save_image

from torch.utils.data import DataLoader
from torchvision import datasets
from torch.autograd import Variable

import torch.nn as nn
import torch.nn.functional as F
import torch

os.makedirs("images", exist_ok=True)

parser = argparse.ArgumentParser()
parser.add_argument("--n_epochs", type=int, default=200, help="number of epochs of training")
parser.add_argument("--batch_size", type=int, default=64, help="size of the batches")
parser.add_argument("--lr", type=float, default=0.0002, help="adam: learning rate")
parser.add_argument("--b1", type=float, default=0.5, help="adam: decay of first order momentum of gradient")
parser.add_argument("--b2", type=float, default=0.999, help="adam: decay of first order momentum of gradient")
parser.add_argument("--n_cpu", type=int, default=8, help="number of cpu threads to use during batch generation")
parser.add_argument("--latent_dim", type=int, default=100, help="dimensionality of the latent space")
parser.add_argument("--num_classes", type=int, default=10, help="number of classes for dataset")
parser.add_argument("--img_size", type=int, default=32, help="size of each image dimension")
parser.add_argument("--channels", type=int, default=1, help="number of image channels")
parser.add_argument("--sample_interval", type=int, default=400, help="interval between image sampling")
opt = parser.parse_args()
print(opt)



def weights_init_normal(m):
    classname = m.__class__.__name__
    if classname.find("Conv") != -1:
        torch.nn.init.normal_(m.weight.data, 0.0, 0.02)
    elif classname.find("BatchNorm") != -1:
        torch.nn.init.normal_(m.weight.data, 1.0, 0.02)
        torch.nn.init.constant_(m.bias.data, 0.0)


class Generator(nn.Module):
    def __init__(self, latent_dim, img_size, channels, num_classes):
        super(Generator, self).__init__()

        self.label_emb = nn.Embedding(num_classes, latent_dim)

        self.init_size = img_size // 4  # Initial size before upsampling
        self.l1 = nn.Sequential(nn.Linear(latent_dim, 128 * self.init_size ** 2))

        self.conv_blocks = nn.Sequential(
            nn.BatchNorm2d(128),
            nn.Upsample(scale_factor=2),
            nn.Conv2d(128, 128, 3, stride=1, padding=1),
            nn.BatchNorm2d(128, 0.8),
            nn.LeakyReLU(0.2, inplace=True),
            nn.Upsample(scale_factor=2),
            nn.Conv2d(128, 64, 3, stride=1, padding=1),
            nn.BatchNorm2d(64, 0.8),
            nn.LeakyReLU(0.2, inplace=True),
            nn.Conv2d(64, channels, 3, stride=1, padding=1),
            nn.Tanh(),
        )

    def forward(self, noise):
        out = self.l1(noise)
        out = out.view(out.shape[0], 128, self.init_size, self.init_size)
        img = self.conv_blocks(out)
        return img


class Discriminator(nn.Module):
    def __init__(self, img_size, channels, num_classes):
        super(Discriminator, self).__init__()

        def discriminator_block(in_filters, out_filters, bn=True):
            """Returns layers of each discriminator block"""
            block = [nn.Conv2d(in_filters, out_filters, 3, 2, 1), nn.LeakyReLU(0.2, inplace=True), nn.Dropout2d(0.25)]
            if bn:
                block.append(nn.BatchNorm2d(out_filters, 0.8))
            return block

        self.conv_blocks = nn.Sequential(
            *discriminator_block(channels, 16, bn=False),
            *discriminator_block(16, 32),
            *discriminator_block(32, 64),
            *discriminator_block(64, 128),
        )

        # The height and width of downsampled image
        ds_size = img_size // 2 ** 4

        # Output layers
        self.adv_layer = nn.Sequential(nn.Linear(128 * ds_size ** 2, 1), nn.Sigmoid())
        self.aux_layer = nn.Sequential(nn.Linear(128 * ds_size ** 2, num_classes + 1), nn.Softmax())

    def forward(self, img):
        out = self.conv_blocks(img)
        out = out.view(out.shape[0], -1)
        validity = self.adv_layer(out)
        label = self.aux_layer(out)

        return validity, label



class SGAN():
    def __init__(self, lr = 0.0002,b1 = 0.5, b2 = 0.999, latent_dim = 100,img_size = 32,channels = 1,num_classes = 10):
        self.lr = lr
        self.b1 = b1
        self.b2 = b2
        self.img_size = img_size
        self.channels = channels
        self.latent_dim = latent_dim
        self.num_classes = num_classes

        # Loss functions
        self.adversarial_loss = torch.nn.BCELoss()
        self.auxiliary_loss = torch.nn.CrossEntropyLoss()

        # Initialize generator and discriminator
        self.generator = Generator(self.latent_dim,self.img_size,self.channels,self.num_classes)
        self.discriminator = Discriminator(self.img_size,self.channels,self.num_classes)

        cuda = False #True if torch.cuda.is_available() else False

        if cuda:
            self.generator.cuda()
            self.discriminator.cuda()
            self.adversarial_loss.cuda()
            self.auxiliary_loss.cuda()
        self.FloatTensor = torch.FloatTensor #torch.cuda.FloatTensor if cuda else torch.FloatTensor
        self.LongTensor = torch.LongTensor #torch.cuda.LongTensor if cuda else torch.LongTensor

        # Initialize weights
        self.generator.apply(weights_init_normal)
        self.discriminator.apply(weights_init_normal)



        # Optimizers
        self.optimizer_G = torch.optim.Adam(self.generator.parameters(), lr=self.lr, betas=(self.b1, self.b2))
        self.optimizer_D = torch.optim.Adam(self.discriminator.parameters(), lr=self.lr, betas=(self.b1, self.b2))



    # ----------
    #  Training
    # ----------
    def train(self, n_epochs,sample_interval):
        for epoch in range(n_epochs):
            for i, (imgs, labels) in enumerate(dataloader):

                batch_size = imgs.shape[0]

                # Adversarial ground truths
                valid = Variable(self.FloatTensor(batch_size, 1).fill_(1.0), requires_grad=False)
                fake = Variable(self.FloatTensor(batch_size, 1).fill_(0.0), requires_grad=False)
                fake_aux_gt = Variable(self.LongTensor(batch_size).fill_(self.num_classes), requires_grad=False)

                # Configure input
                real_imgs = Variable(imgs.type(self.FloatTensor))
                labels = Variable(labels.type(self.LongTensor))

                # -----------------
                #  Train Generator
                # -----------------

                self.optimizer_G.zero_grad()

                # Sample noise and labels as generator input
                z = Variable(self.FloatTensor(np.random.normal(0, 1, (batch_size, self.latent_dim))))

                # Generate a batch of images
                gen_imgs = self.generator(z)

                # Loss measures generator's ability to fool the discriminator
                validity, _ = self.discriminator(gen_imgs)
                g_loss = self.adversarial_loss(validity, valid)

                g_loss.backward()
                self.optimizer_G.step()

                # ---------------------
                #  Train Discriminator
                # ---------------------

                optimizer_D.zero_grad()

                # Loss for real images
                real_pred, real_aux = self.discriminator(real_imgs)
                d_real_loss = (self.adversarial_loss(real_pred, valid) + self.auxiliary_loss(real_aux, labels)) / 2

                # Loss for fake images
                fake_pred, fake_aux = self.discriminator(gen_imgs.detach())
                d_fake_loss = (self.adversarial_loss(fake_pred, fake) + self.auxiliary_loss(fake_aux, fake_aux_gt)) / 2

                # Total discriminator loss
                d_loss = (d_real_loss + d_fake_loss) / 2

                # Calculate discriminator accuracy
                pred = np.concatenate([real_aux.data.cpu().numpy(), fake_aux.data.cpu().numpy()], axis=0)
                gt = np.concatenate([labels.data.cpu().numpy(), fake_aux_gt.data.cpu().numpy()], axis=0)
                d_acc = np.mean(np.argmax(pred, axis=1) == gt)

                d_loss.backward()
                self.optimizer_D.step()

                print(
                    "[Epoch %d/%d] [Batch %d/%d] [D loss: %f, acc: %d%%] [G loss: %f]"
                    % (epoch, n_epochs, i, len(dataloader), d_loss.item(), 100 * d_acc, g_loss.item())
                )

                batches_done = epoch * len(dataloader) + i
                if batches_done % sample_interval == 0:
                    save_image(gen_imgs.data[:25], "images/%d.png" % batches_done, nrow=5, normalize=True)

'''


# Configure data loader
os.makedirs("../../data/mnist", exist_ok=True)
dataloader = torch.utils.data.DataLoader(
    datasets.MNIST(
        "../../data/mnist",
        train=True,
        download=True,
        transform=transforms.Compose(
            [transforms.Resize(opt.img_size), transforms.ToTensor(), transforms.Normalize([0.5], [0.5])]
        ),
    ),
    batch_size=opt.batch_size,
    shuffle=True,
)'''
