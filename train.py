from loss import StyleLoss, ContentLoss
from utils import Normalization, image_loader, imshow
import torch.nn.functional as F
import torch.nn as nn
import torch.optim as optim
import torch 

# desired depth layers to compute style/content losses :
content_layers_default = ['conv_4']
style_layers_default = ['conv_1', 'conv_2', 'conv_3', 'conv_4', 'conv_5']
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

def get_style_model_and_losses(cnn, normalization_mean, normalization_std,
                               style_img, content_img,
                               content_layers=content_layers_default,
                               style_layers=style_layers_default):
    """


    Args:
        cnn (torch.nn): The VGG-19 model use to train
        normalization_mean (torch.tensor): mean tensor to normalize the image for VGG-19
        normalization_std (torch.tensor): std tensor to normalize the image for VGG-19
        style_img (torch.tensor): the style image as tensor
        content_img (torch.tensor): the original image as tensor
        content_layers (list, optional): List of layers to compute content loss. Defaults to content_layers_default.
        style_layers (list, optional): List of layers to compute style loss_. Defaults to style_layers_default.

    Returns:
        model (torch.nn): model including loss module for passing input and calculating loss functions, cutting out unnecessary parts
        style_losses (StyleLoss): module for calculating style loss
        content_losses (ContentLoss): module for calculating content loss

    """
    # normalization module
    normalization = Normalization(normalization_mean, normalization_std).to(device)

    # store content losses and style loses module forward
    content_losses, style_losses = [], []

    model = nn.Sequential(normalization)

    i = 0  # increment every time we see a conv
    # nameing layer according to conv
    for layer in cnn.children():
        if isinstance(layer, nn.Conv2d):
            i += 1
            name = 'conv_{}'.format(i)
        elif isinstance(layer, nn.ReLU):
            name = 'relu_{}'.format(i)
            layer = nn.ReLU(inplace=False)
        elif isinstance(layer, nn.MaxPool2d):
            name = 'pool_{}'.format(i)
        elif isinstance(layer, nn.BatchNorm2d):
            name = 'bn_{}'.format(i)
        else:
            raise RuntimeError('Unrecognized layer: {}'.format(layer.__class__.__name__))

        model.add_module(name, layer) # add layer to model

        if name in content_layers:
            # add content loss:
            target = model(content_img).detach()
            content_loss = ContentLoss(target)
            model.add_module("content_loss_{}".format(i), content_loss) # add detached loss module to model
            content_losses.append(content_loss)

        if name in style_layers:
            # add style loss:
            target_feature = model(style_img).detach()
            style_loss = StyleLoss(target_feature)
            model.add_module("style_loss_{}".format(i), style_loss) # add detached loss module to model
            style_losses.append(style_loss)

    # now we trim off the layers after the last content and style losses
    for i in range(len(model) - 1, -1, -1):
        if isinstance(model[i], ContentLoss) or isinstance(model[i], StyleLoss):
            break

    model = model[:(i + 1)]

    return model, style_losses, content_losses

def get_input_optimizer(input_img):
    """
    Returns an optimizer for updating the input image.

    Args:
        input_img (torch.Tensor): The input image tensor.

    Returns:
        torch.optim.Optimizer: The optimizer for updating the input image.

    """
    optimizer = optim.LBFGS([input_img])
    return optimizer


def run_style_transfer(cnn, normalization_mean, normalization_std,
                       content_img, style_img, input_img, num_steps=150,
                       style_weight=100000, content_weight=5):
    """_summary_

    Args:
        cnn (torch.nn): The VGG-19 model use to train
        normalization_mean (torch.tensor): mean tensor to normalize the image for VGG-19
        normalization_std (torch.tensor): std tensor to normalize the image for VGG-19
        style_img (torch.tensor): the style image as tensor
        content_img (torch.tensor): the original image as tensor
        input_img (torch.tensor): Initialize is a copy of the original image. Calculation and backpropagation operations will be performed on this image to obtain the generated image.
        num_steps (int, optional): numer steps of iterations. Defaults to 200.
        style_weight (int, optional): weight for style loss. Defaults to 100000.
        content_weight (int, optional): weights for content loss. Defaults to 5.

    Returns:
        input_img (torch.tensor): the generated image.
    """

    # build model and loss module
    print('Building the style transfer model..')
    model, style_losses, content_losses = get_style_model_and_losses(cnn,
        normalization_mean, normalization_std, style_img, content_img)

    # set up require grad for input image, and not for model's weights and bias
    input_img.requires_grad_(True)
    model.eval()
    model.requires_grad_(False)
    optimizer = get_input_optimizer(input_img)

    # start optimizing
    print('Optimizing..')
    run = [0]
    while run[0] <= num_steps:

        def closure():
            with torch.no_grad():
                input_img.clamp_(0, 1)

            optimizer.zero_grad()
            model(input_img)
            style_score, content_score = 0, 0

            # calculate style loss and content loss
            for sl in style_losses:
                style_score += sl.loss
            for cl in content_losses:
                content_score += cl.loss

            # calculate the final loss based on content loss and style loss
            style_score *= style_weight
            content_score *= content_weight
            loss = style_score + content_score

            # backward
            loss.backward()

            run[0] += 1
            if run[0] % 50 == 0:
                print("run {}:".format(run))
                print('Style Loss : {:4f} Content Loss: {:4f}'.format(
                    style_score.item(), content_score.item()))
                print()

            return style_score + content_score

        optimizer.step(closure)

    with torch.no_grad():
        input_img.clamp_(0, 1)

    return input_img