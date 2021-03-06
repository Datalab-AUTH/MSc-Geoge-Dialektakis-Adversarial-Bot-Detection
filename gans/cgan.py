"""
Import necessary libraries to create a generative adversarial network
The code is developed using the PyTorch library
"""
import pickle
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score
from sklearn.preprocessing import MinMaxScaler
import joblib
import matplotlib.pyplot as plt
from sdv.evaluation import evaluate
from sdv.metrics.tabular import KSTest
from statistics import mean
import helper_functions.transform_booleans as transform_bool
import warnings
warnings.filterwarnings('ignore')

"""
Network Architectures
The following are the discriminator and generator architectures
"""


class Discriminator(nn.Module):
    def __init__(self):
        super(Discriminator, self).__init__()
        self.num_classes = 2
        self.num_features = 310
        self.prob = 0.2
        # embedding layer of the class labels (num_of_classes * encoding_size of each word)
        self.label_emb = nn.Embedding(self.num_classes, self.num_classes)

        self.model = nn.Sequential(
            nn.Linear(self.num_features+self.num_classes, 400),
            nn.LeakyReLU(0.2, inplace=True),
            nn.Dropout(self.prob),
            nn.Linear(400, 1000),
            nn.LeakyReLU(0.2, inplace=True),
            nn.Dropout(self.prob),
            nn.Linear(1000, 1),
            nn.Sigmoid()
        )

    def forward(self, x, labels):
        x = x.view(x.size(0), self.num_features)
        c = self.label_emb(labels)
        x = torch.cat([x, c], 1)
        out = self.model(x)
        return out.squeeze()


class Generator(nn.Module):
    def __init__(self):
        super(Generator, self).__init__()
        self.num_classes = 2
        self.num_features = 310
        self.noise = 128
        # embedding layer of the class labels (num_of_classes * encoding_size of each word)
        self.label_emb = nn.Embedding(self.num_classes, self.num_classes)

        self.model = nn.Sequential(
            nn.Linear(self.noise+self.num_classes, 500),
            nn.ReLU(inplace=True),
            nn.Linear(500, 1000),
            nn.ReLU(inplace=True),
            nn.Linear(1000, self.num_features),
            nn.Sigmoid()
        )

    def forward(self, z, labels):
        z = z.view(z.size(0), self.noise)
        c = self.label_emb(labels)
        x = torch.cat([z, c], 1)
        out = self.model(x)
        return out.view(-1, 1, 1, self.num_features)


def prepare_data(batch_size=512, bots=True):
    bots_df = pickle.load(open('../data/original_data/train_binary_data_bots', 'rb'))
    humans_df = pickle.load(open('../data/original_data/train_binary_data_humans', 'rb'))

    # Concatenate human and bot training samples
    pdList = [bots_df, humans_df]
    df = pd.concat(pdList)

    # Shuffle the dataframe
    df = df.sample(frac=1)

    #df = df.sample(n=1000)
    y = df['label']

    if bots:
        df_filtered = df[df['label'] == 1]
    else:
        df_filtered = df[df['label'] == 0]

    df = df.drop(['label'], axis=1)
    df_filtered = df_filtered.drop(['label'], axis=1)

    # Scale our data in the range of (0, 1)
    scaler = MinMaxScaler()
    df_scaled = scaler.fit_transform(X=df)

    # Store scaler for later use
    scaler_filename = "conditional_gan/scaler.save"
    joblib.dump(scaler, scaler_filename)

    # Transform dataframe into pytorch Tensor
    train = TensorDataset(torch.Tensor(df_scaled), torch.Tensor(np.array(y)))
    train_loader = DataLoader(dataset=train, batch_size=batch_size, shuffle=True)
    return train_loader, df, df_filtered


def train_gan(epochs=100):
    """
    Determine if any GPUs are available
    """
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    """
    Hyperparameter settings
    """
    lr = 0.0002
    bs = 64
    loss = nn.BCELoss()

    # Model
    G = Generator().to(device)
    D = Discriminator().to(device)

    G_optimizer = optim.Adam(G.parameters(), lr=lr, betas=(0.5, 0.999))
    D_optimizer = optim.Adam(D.parameters(), lr=lr, betas=(0.5, 0.999))

    # Load our data
    train_loader, _, _ = prepare_data(batch_size=bs)

    """
    Network training procedure
    Every step both the loss for disciminator and generator is updated
    Discriminator aims to classify reals and fakes
    Generator aims to generate bot accounts as realistic as possible
    """
    mean_D_loss = []
    mean_G_loss = []
    D_acc = []
    for epoch in range(epochs):
        acc = []
        epoch_D_loss = []
        epoch_G_loss = []
        #labels = train_loader[1]
        for idx, train_data in enumerate(train_loader):
            idx += 1

            # Training the discriminator
            # Real inputs are actual samples from the original dataset
            # Fake inputs are from the generator
            # Real inputs should be classified as 1 and fake as 0

            # Fetch a batch of real samples from training data
            # Feed real samples to Discriminator
            real_inputs = train_data[0].to(device)
            class_labels = train_data[1].to(torch.int64).to(device)
            real_outputs = D(real_inputs, class_labels)
            real_labels = torch.ones(real_inputs.shape[0], 1).to(device)

            # Make a batch of fake samples using Generator
            # Feed fake samples to Discriminator
            noise = (torch.rand(real_inputs.shape[0], 128) - 0.5) / 0.5
            noise = noise.to(device)

            fake_class_labels = torch.randint(0, 2, (real_inputs.shape[0],)).to(device)
            fake_inputs = G(noise, fake_class_labels)

            fake_outputs = D(fake_inputs, fake_class_labels)
            fake_labels = torch.zeros(fake_inputs.shape[0], 1).to(device)

            # Combine the two loss values
            # use combined loss to update Discriminator
            outputs = torch.cat((real_outputs, fake_outputs), 0).view(-1, 1)
            targets = torch.cat((real_labels, fake_labels), 0)

            # Just for evaluation and monitoring purposes
            predictions = outputs.cpu().detach().numpy()
            predictions = np.round(predictions)
            labels = targets.cpu().detach().numpy()

            D_loss = loss(outputs, targets)
            D_optimizer.zero_grad()
            D_loss.backward()
            D_optimizer.step()

            # Training the Generator
            # For the Generator, the goal is to make the Discriminator believe everything is 1
            noise = (torch.rand(real_inputs.shape[0], 128) - 0.5) / 0.5
            noise = noise.to(device)

            # Make a batch of fake samples using Generator
            # Feed fake samples to Discriminator, compute reverse loss and use it to update the Generator
            fake_inputs = G(noise, fake_class_labels)
            fake_outputs = D(fake_inputs, fake_class_labels).view(-1, 1)
            fake_targets = torch.ones([fake_inputs.shape[0], 1]).to(device)
            G_loss = loss(fake_outputs, fake_targets)
            G_optimizer.zero_grad()
            G_loss.backward()
            G_optimizer.step()

            if idx % 100 == 0 or idx == len(train_loader):
                epoch_D_loss.append(D_loss.item())
                epoch_G_loss.append(G_loss.item())
                D_accuracy = accuracy_score(labels, predictions)
                acc.append(D_accuracy)

        print('Epoch {} -- Discriminator mean Accuracy: {:.5f}'.format(epoch, mean(acc)))
        print('Epoch {} -- Discriminator mean loss: {:.5f}'.format(epoch, mean(epoch_D_loss)))
        print('Epoch {} -- Generator mean loss: {:.5f}'.format(epoch, mean(epoch_G_loss)))
        print('~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~')
        mean_D_loss.append(mean(epoch_D_loss))
        mean_G_loss.append(mean(epoch_G_loss))
        D_acc.append(mean(acc))

    # loss plots
    plt.figure(figsize=(10, 7))
    plt.plot(mean_D_loss, color='blue', label='Discriminator loss')
    plt.plot(mean_G_loss, color='red', label='Generator loss')
    plt.xlabel('Epochs')
    plt.ylabel('Loss')
    plt.legend()
    plt.savefig('conditional_gan/cond_gan_loss.png')
    plt.show()

    plt.figure(figsize=(10, 7))
    plt.plot(D_acc, color='blue', label='Discriminator accuracy')
    plt.xlabel('Epochs')
    plt.ylabel('Accuracy')
    plt.legend()
    plt.savefig('conditional_gan/cond_discriminator_acc.png')
    plt.show()

    torch.save(G, 'conditional_gan/Conditional_Generator_save.pth')
    print('Generator saved.')


"""
A function that loads a trained Generator model and uses it to create synthetic samples
"""


def generate_synthetic_samples(num_of_samples=100, num_of_features=310, num_of_classes=2, bots=False):
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    # Load initial data
    _, _, real_data = prepare_data(bots=bots)

    generator = torch.load('conditional_gan/Conditional_Generator_save.pth')
    # Generate points in the latent space
    noise = (torch.rand(num_of_samples, 128) - 0.5) / 0.5
    noise = noise.to(device)

    # Create class labels
    if bots:
        class_labels = torch.randint(1, num_of_classes, (num_of_samples,)).to(device)
    else:
        class_labels = torch.randint(0, num_of_classes-1, (num_of_samples,)).to(device)

    # Pass latent points and class labels through our Generator to produce synthetic samples
    synthetic_samples = generator(noise, class_labels)

    # Transform pytorch tensor to numpy array
    synthetic_samples = synthetic_samples.cpu().detach().numpy()
    synthetic_samples = synthetic_samples.reshape(num_of_samples, num_of_features)
    class_labels = class_labels.cpu().detach().numpy()
    class_labels = class_labels.reshape(num_of_samples, 1)

    # Load saved min_max_scaler for inverse transformation of the generated data
    scaler = joblib.load("conditional_gan/scaler.save")
    synthetic_data = scaler.inverse_transform(synthetic_samples)
    synthetic_data = pd.DataFrame(data=synthetic_data, columns=real_data.columns)

    synthetic_samples = synthetic_data.copy(deep=True)
    # Insert column containing labels
    synthetic_data.insert(loc=310, column='label', value=class_labels, allow_duplicates=True)

    synthetic_data = transform_bool.transform(synthetic_data)

    return synthetic_data


def create_final_synthetic_dataset(test=False):
    if test:
        synthetic_data_bots = generate_synthetic_samples(num_of_samples=int(13688/2), bots=True)
        synthetic_data_humans = generate_synthetic_samples(num_of_samples=int(13688/2), bots=False)
    else:
        synthetic_data_bots = generate_synthetic_samples(num_of_samples=30000, bots=True)
        synthetic_data_humans = generate_synthetic_samples(num_of_samples=30000, bots=False)

    # Concatenate human and bot synthetic samples
    pdList = [synthetic_data_bots, synthetic_data_humans]
    final_df = pd.concat(pdList)

    # Shuffle the dataframe
    final_df = final_df.sample(frac=1)
    if test:
        pickle.dump(final_df, open('../data/synthetic_data/conditional_gan/synthetic_binary_test_data', 'wb'))
    else:
        pickle.dump(final_df, open('../data/synthetic_data/conditional_gan/synthetic_binary_train_data', 'wb'))
    return final_df


def evaluate_synthetic_data():
    real_data = pickle.load(open('../data/original_data/train_multiclass_data', 'rb'))
    real_data = real_data.drop(['label'], axis=1)

    test_data = pickle.load(open('../data/original_data/test_multiclass_data', 'rb'))
    test_data = test_data.drop(['label'], axis=1)

    print('\n~~~~~~~~~~~~~~ Synthetic Data Evaluation ~~~~~~~~~~~~~~')

    print('\n~~~~~~~~~~~~~~ Evaluating method of creating that many samples to reach 30K per class ~~~~~~~~~~~~~~')
    synthetic_data = pickle.load(
        open('../data/synthetic_data/cgan/synthetic_data_2_to_1', 'rb'))

    synthetic_data = synthetic_data.drop(['label'], axis=1)

    ks = KSTest.compute(synthetic_data, real_data)
    ks_test_data = KSTest.compute(synthetic_data, test_data)
    print('Inverted Kolmogorov-Smirnov D statistic on Train Data: {}'.format(ks))
    print('Inverted Kolmogorov-Smirnov D statistic on Test Data: {}'.format(ks_test_data))

    kl_divergence = evaluate(synthetic_data, real_data, metrics=['ContinuousKLDivergence'])
    print('Continuous Kullback???Leibler Divergence: {}'.format(kl_divergence))
    """
    print('\n~~~~~~~~~~~~~~ Evaluating method of creating two to one synthetic samples  per class ~~~~~~~~~~~~~~')
    synthetic_data = pickle.load(
        open('../data/synthetic_data/cgan/synthetic_data_2_to_1', 'rb'))

    synthetic_data = synthetic_data.drop(['label'], axis=1)

    ks = KSTest.compute(synthetic_data, real_data)
    ks_test_data = KSTest.compute(synthetic_data, test_data)
    print('Inverted Kolmogorov-Smirnov D statistic on Train Data: {}'.format(ks))
    print('Inverted Kolmogorov-Smirnov D statistic on Test Data: {}'.format(ks_test_data))
    """
    # kl_divergence = evaluate(synthetic_data, real_data, metrics=['ContinuousKLDivergence'])
    # print('Continuous Kullback???Leibler Divergence: {}'.format(kl_divergence))


#train_gan(epochs=300)

evaluate_synthetic_data()
