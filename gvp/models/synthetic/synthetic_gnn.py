from argparse import ArgumentParser
from gvp import SyntheticDataModule
import pytorch_lightning as pl
import numpy as np

import torch
import torch.nn.functional as F
from torch import nn, optim
from torch_geometric.nn import GCNConv, global_max_pool
from torch_geometric import transforms
from torchmetrics.functional import mean_squared_error
from pytorch_lightning.loggers import WandbLogger
from pytorch_lightning.callbacks import ModelCheckpoint
import wandb

from pathlib import Path

import gvp

class ExtendedPPF:
    def __init__(self, norm=True, cat=True):
        self.norm = norm
        self.cat = cat

        self.ppf = transforms.PointPairFeatures(cat=False)
        self.distance = transforms.Distance(norm=norm, cat=False)

    def __call__(self, data):
        existing_features = data.edge_attr

        ppf_features = self.ppf(data).edge_attr
        ppf_features = torch.cos(ppf_features)
        dist_features = self.distance(data).edge_attr


        new_features = torch.cat([dist_features, ppf_features[:, 1:]], dim=-1)
        
        if existing_features is not None and self.cat:
            data.edge_attr = torch.cat([existing_features, new_features], dim=-1)
        else:
            data.edge_attr = new_features

        return data

class SyntheticGNN(pl.LightningModule):
    def __init__(self, num_node_features):
        super().__init__()
        self.layers = nn.ModuleList([
            GCNConv(num_node_features, 32),
            GCNConv(32, 32),
            GCNConv(32, 32)
        ])
        self.classifier = nn.Linear(32, 1)

    def forward(self, data):
        x = data.x
        edge_index = data.edge_index
        batch = data.batch

        for layer in self.layers:
            x = layer(x, edge_index)
            x = F.relu(x)
        
        x = global_max_pool(x, batch)

        x = self.classifier(x)

        return x

    def shared_step(self, batch):
        data, y = batch, batch.y
        y_hat = self(data).view(-1)
        loss = mean_squared_error(y_hat, y)

        return loss

    def training_step(self, batch, batch_idx):
        loss = self.shared_step(batch)
        return loss

    def validation_step(self, batch, batch_idx):
        loss = self.shared_step(batch)

        self.log("val_loss", loss)

    def test_step(self, batch, batch_idx):
        loss = self.shared_step(batch)

        self.log("test_loss", loss)

    def configure_optimizers(self):
        return optim.Adam(self.parameters())




# TODO: Complete Synthetic GVP model
# class SyntheticGVP(nn.Module):
#     def __init__(
#         self,
#         feats_x_in,
#         vectors_x_in,
#         feats_edge_in,
#         vectors_edge_in,
#         feats_h,
#         vectors_h,
#         dropout=0.0,
#         residual=False,
#         vector_dim=3,
#         verbose=0
#     ):
#         super().__init__()

#         self.feats_x_in = feats_x_in
#         self.vectors_x_in = vectors_x_in
#         self.feats_edge_in = feats_edge_in
#         self.vectors_edge_in = vectors_edge_in
#         self.feats_h = feats_h
#         self.vectors_h = vectors_h
#         self.dropout = dropout
#         self.residual = residual
#         self.vector_dim = vector_dim
#         self.verbose = verbose

#         self.layers = nn.ModuleList([
#             GVP_MPNN(
#                 feats_x_in = feats_x_in,
#                 vectors_x_in = vectors_x_in,
#                 feats_x_out = feats_h,
#                 vectors_x_out = vectors_h,
#                 feats_edge_in = feats_edge_in,
#                 vectors_edge_in = vectors_edge_in,
#                 feats_edge_out = feats_h,
#                 vectors_edge_out = vectors_h,
#                 dropout = dropout,
#                 residual = residual,
#                 vector_dim = vector_dim,
#                 verbose = verbose 
#             ),
#             GVP_MPNN(
#                 feats_x_in = feats_h,
#                 vectors_x_in = vectors_h,
#                 feats_x_out = feats_h,
#                 vectors_x_out = vectors_h,
#                 feats_edge_in = feats_h,
#                 vectors_edge_in = vectors_h,
#                 feats_edge_out = feats_h,
#                 vectors_edge_out = vectors_h,
#                 dropout = dropout,
#                 residual = residual,
#                 vector_dim = vector_dim,
#                 verbose = verbose
#             ),
#             GVP_MPNN(
#                 feats_x_in = feats_h,
#                 vectors_x_in = vectors_h,
#                 feats_x_out = feats_h,
#                 vectors_x_out = vectors_h,
#                 feats_edge_in = feats_h,
#                 vectors_edge_in = vectors_h,
#                 feats_edge_out = feats_h,
#                 vectors_edge_out = vectors_h,
#                 dropout = dropout,
#                 residual = residual,
#                 vector_dim = vector_dim,
#                 verbose = verbose
#             )
#         ]
#         )

#         self.dense = nn.Linear(feats_h + (vectors_h * vector_dim), 1)
    
#     def forward(self, data):
#         x = data.x
#         edge_index = data.edge_index
#         edge_attr = data.edge_attr
        
#         for layer in self.layers:
#             out = layer(x, edge_index, edge_attr)

#         out = self.dense(out)

#         return out

def main():
    # ------------
    # args
    # ------------
    parser = ArgumentParser()
    parser.add_argument('--batch_size', default=64, type=int)
    parser.add_argument('--num_workers', default=2, type=int)
    parser.add_argument('--task', default='off_center', type=str)
    parser = pl.Trainer.add_argparse_args(parser)
    args = parser.parse_args()

    # ------------
    # data
    # ------------
    data_dir = Path(gvp.__file__).parents[1] / "data/synthetic"

    transform = transforms.Compose([
        transforms.KNNGraph(k=10),
        ExtendedPPF()
    ])
    dm = SyntheticDataModule(data_dir, args.batch_size, args.task, transform, num_workers=args.num_workers)

    # ------------
    # model
    # ------------
    model = SyntheticGNN(4)

    # ------------
    # training
    # ------------
    wandb_logger = WandbLogger(name="SyntheticGNN", project="GVP", reinit=True)
    checkpoint_callback = ModelCheckpoint(
        monitor="val_loss",
        dirpath="model_checkpoints",
        filename="SyntheticGNN-{args.task}-{epoch:02d}-{val_loss:.2f}",
        save_weights_only=True,
        save_top_k=3,
        mode="min",
    )
    trainer = pl.Trainer.from_argparse_args(args, max_epochs=100, gpus=1, logger=wandb_logger, callbacks=[checkpoint_callback])
    trainer.fit(model, dm)

    # ------------
    # testing
    # ------------
    result = trainer.test(datamodule=dm)
    print(result)

    wandb.finish()
    
if __name__ == "__main__":
    main()