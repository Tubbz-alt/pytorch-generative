"""TODO(eugenhotaj): explain."""

import torch
from torch import nn

from pytorch_generative.models import vaes


class VAE(nn.Module):
    """The Variational Autoencoder model."""

    def __init__(
        self,
        in_channels=1,
        out_channels=1,
        latent_channels=2,
        hidden_channels=128,
        residual_channels=32,
    ):
        """Initializes a new VAE instance.

        Args:
            in_channels: Number of input channels.
            out_channels: Number of output channels.
            latent_channels: Number of channels for each latent variable.
            hidden_channels: Number of channels in (non residual block) hidden layers.
            residual_channels: Number of hidden channels in residual blocks.
        """
        super().__init__()

        self._latent_channels = latent_channels
        self._stride = 4

        self._encoder = vaes.Encoder(
            in_channels=in_channels,
            out_channels=2 * self._latent_channels,
            hidden_channels=hidden_channels,
            residual_channels=residual_channels,
            n_residual_blocks=2,
            stride=self._stride,
        )
        self._decoder = vaes.Decoder(
            in_channels=self._latent_channels,
            out_channels=out_channels,
            hidden_channels=hidden_channels,
            residual_channels=residual_channels,
            n_residual_blocks=2,
            stride=self._stride,
        )

    def forward(self, x):
        # TODO(eugenhotaj): Maybe take in_size as input arguments in sample()?
        self._in_size = x.shape[2]  # Save for later sampling.
        # NOTE: We use log_var (instead of var or std) for stability and easier
        # optimization during training.
        mean, log_var = torch.split(self._encoder(x), self._latent_channels, dim=1)
        var = torch.exp(log_var)
        latents = mean + torch.sqrt(var) * torch.randn_like(var)
        # NOTE: This KL divergence is only applicable under the assumption that the
        # prior ~ N(0, 1) and the latents are Gaussian.
        kl_div = -0.5 * (1 + log_var - mean ** 2 - var).mean(dim=(1, 2, 3))
        return self._decoder(latents), kl_div

    def sample(self, n_samples):
        """Generates a batch of n_samples."""
        device = next(self.parameters()).device
        latent_size = self._in_size // 2 ** (self._stride // 2)
        shape = (n_samples, self._latent_channels, latent_size, latent_size)
        latents = torch.randn(shape, device=device)
        return self._decoder(latents)


def reproduce(
    n_epochs=457, batch_size=128, log_dir="/tmp/run", device="cuda", debug_loader=None
):
    """Training script with defaults to reproduce results.

    The code inside this function is self contained and can be used as a top level
    training script, e.g. by copy/pasting it into a Jupyter notebook.

    Args:
        n_epochs: Number of epochs to train for.
        batch_size: Batch size to use for training and evaluation.
        log_dir: Directory where to log trainer state and TensorBoard summaries.
        device: Device to train on (either 'cuda' or 'cpu').
        debug_loader: Debug DataLoader which replaces the default training and
            evaluation loaders if not 'None'. Do not use unless you're writing unit
            tests.
    """
    from torch import optim
    from torch.nn import functional as F
    from torch.optim import lr_scheduler
    from torch.utils import data
    from torchvision import datasets
    from torchvision import transforms

    from pytorch_generative import trainer
    from pytorch_generative import models

    transform = transforms.ToTensor()
    train_loader = debug_loader or data.DataLoader(
        datasets.MNIST("/tmp/data", train=True, download=True, transform=transform),
        batch_size=batch_size,
        shuffle=True,
        num_workers=8,
    )
    test_loader = debug_loader or data.DataLoader(
        datasets.MNIST("/tmp/data", train=False, download=True, transform=transform),
        batch_size=batch_size,
        num_workers=8,
    )

    model = models.VAE(
        in_channels=1,
        out_channels=1,
        latent_channels=2,
        hidden_channels=128,
        residual_channels=32,
    )
    optimizer = optim.Adam(model.parameters(), lr=1e-3)
    scheduler = lr_scheduler.MultiplicativeLR(optimizer, lr_lambda=lambda _: 0.999977)

    def loss_fn(x, _, preds):
        preds, vae_loss = preds
        recon_loss = F.binary_cross_entropy_with_logits(preds, x, reduction="none")
        recon_loss = recon_loss.mean(dim=(1, 2, 3))
        loss = recon_loss + vae_loss
        return {
            "recon_loss": recon_loss.mean(),
            "vae_loss": vae_loss.mean(),
            "loss": loss.mean(),
        }

    def sample_fn(model):
        return torch.sigmoid(model.sample(n_samples=16))

    model_trainer = trainer.Trainer(
        model=model,
        loss_fn=loss_fn,
        optimizer=optimizer,
        train_loader=train_loader,
        eval_loader=test_loader,
        lr_scheduler=scheduler,
        sample_epochs=5,
        sample_fn=sample_fn,
        log_dir=log_dir,
        device=device,
    )
    model_trainer.interleaved_train_and_eval(n_epochs)
