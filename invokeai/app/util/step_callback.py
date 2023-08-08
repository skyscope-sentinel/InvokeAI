import torch
from PIL import Image
from invokeai.app.models.exceptions import CanceledException
from invokeai.app.models.image import ProgressImage
from ..invocations.baseinvocation import InvocationContext
from ...backend.util.util import image_to_dataURL
from ...backend.stable_diffusion import PipelineIntermediateState
from invokeai.app.services.config import InvokeAIAppConfig
from ...backend.model_management.models import BaseModelType


def sample_to_lowres_estimated_image(samples, latent_rgb_factors, smooth_matrix=None):
    latent_image = samples[0].permute(1, 2, 0) @ latent_rgb_factors

    if smooth_matrix is not None:
        latent_image = latent_image.unsqueeze(0).permute(3, 0, 1, 2)
        latent_image = torch.nn.functional.conv2d(latent_image, smooth_matrix.reshape((1, 1, 3, 3)), padding=1)
        latent_image = latent_image.permute(1, 2, 3, 0).squeeze(0)

    latents_ubyte = (
        ((latent_image + 1) / 2).clamp(0, 1).mul(0xFF).byte()  # change scale from -1..1 to 0..1  # to 0..255
    ).cpu()

    return Image.fromarray(latents_ubyte.numpy())


def stable_diffusion_step_callback(
    context: InvocationContext,
    intermediate_state: PipelineIntermediateState,
    node: dict,
    source_node_id: str,
    base_model: BaseModelType,
):
    if context.services.queue.is_canceled(context.graph_execution_state_id):
        raise CanceledException

    # Some schedulers report not only the noisy latents at the current timestep,
    # but also their estimate so far of what the de-noised latents will be. Use
    # that estimate if it is available.
    if intermediate_state.predicted_original is not None:
        sample = intermediate_state.predicted_original
    else:
        sample = intermediate_state.latents

    # TODO: This does not seem to be needed any more?
    # # txt2img provides a Tensor in the step_callback
    # # img2img provides a PipelineIntermediateState
    # if isinstance(sample, PipelineIntermediateState):
    #     # this was an img2img
    #     print('img2img')
    #     latents = sample.latents
    #     step = sample.step
    # else:
    #     print('txt2img')
    #     latents = sample
    #     step = intermediate_state.step

    # TODO: only output a preview image when requested

    if base_model in [BaseModelType.StableDiffusionXL, BaseModelType.StableDiffusionXLRefiner]:
        sdxl_latent_rgb_factors = torch.tensor(
            [
                #   R        G        B
                [0.3816, 0.4930, 0.5320],
                [-0.3753, 0.1631, 0.1739],
                [0.1770, 0.3588, -0.2048],
                [-0.4350, -0.2644, -0.4289],
            ],
            dtype=sample.dtype,
            device=sample.device,
        )

        sdxl_smooth_matrix = torch.tensor(
            [
                # [ 0.0478,  0.1285,  0.0478],
                # [ 0.1285,  0.2948,  0.1285],
                # [ 0.0478,  0.1285,  0.0478],
                [0.0358, 0.0964, 0.0358],
                [0.0964, 0.4711, 0.0964],
                [0.0358, 0.0964, 0.0358],
            ],
            dtype=sample.dtype,
            device=sample.device,
        )

        image = sample_to_lowres_estimated_image(sample, sdxl_latent_rgb_factors, sdxl_smooth_matrix)
    else:
        # origingally adapted from code by @erucipe and @keturn here:
        # https://discuss.huggingface.co/t/decoding-latents-to-rgb-without-upscaling/23204/7

        # these updated numbers for v1.5 are from @torridgristle
        v1_5_latent_rgb_factors = torch.tensor(
            [
                #    R        G        B
                [0.3444, 0.1385, 0.0670],  # L1
                [0.1247, 0.4027, 0.1494],  # L2
                [-0.3192, 0.2513, 0.2103],  # L3
                [-0.1307, -0.1874, -0.7445],  # L4
            ],
            dtype=sample.dtype,
            device=sample.device,
        )

        image = sample_to_lowres_estimated_image(sample, v1_5_latent_rgb_factors)

    (width, height) = image.size
    width *= 8
    height *= 8

    dataURL = image_to_dataURL(image, image_format="JPEG")

    context.services.events.emit_generator_progress(
        graph_execution_state_id=context.graph_execution_state_id,
        node=node,
        source_node_id=source_node_id,
        progress_image=ProgressImage(width=width, height=height, dataURL=dataURL),
        step=intermediate_state.step,
        total_steps=node["steps"],
    )
