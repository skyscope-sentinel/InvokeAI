import bitsandbytes as bnb
import torch

# This file contains utils for working with models that use bitsandbytes LLM.int8() quantization.
# The utils in this file are partially inspired by:
# https://github.com/Lightning-AI/pytorch-lightning/blob/1551a16b94f5234a4a78801098f64d0732ef5cb5/src/lightning/fabric/plugins/precision/bitsandbytes.py


# NOTE(ryand): All of the custom state_dict manipulation logic in this file is pretty hacky. This could be made much
# cleaner by re-implementing bnb.nn.Linear8bitLt with proper use of buffers and less magic. But, for now, we try to
# stick close to the bitsandbytes classes to make interoperability easier with other models that might use bitsandbytes.


class InvokeLinear8bitLt(bnb.nn.Linear8bitLt):
    def _load_from_state_dict(
        self,
        state_dict: dict[str, torch.Tensor],
        prefix: str,
        local_metadata,
        strict,
        missing_keys,
        unexpected_keys,
        error_msgs,
    ):
        weight = state_dict.pop(prefix + "weight")
        bias = state_dict.pop(prefix + "bias", None)

        # See `bnb.nn.Linear8bitLt._save_to_state_dict()` for the serialization logic of SCB and weight_format.
        scb = state_dict.pop(prefix + "SCB", None)
        # weight_format is unused, but we pop it so we can validate that there are no unexpected keys.
        _weight_format = state_dict.pop(prefix + "weight_format", None)

        # TODO(ryand): Technically, we should be using `strict`, `missing_keys`, `unexpected_keys`, and `error_msgs`
        # rather than raising an exception to correctly implement this API.
        assert len(state_dict) == 0

        if scb is not None:
            # We are loading a pre-quantized state dict.
            self.weight = bnb.nn.Int8Params(
                data=weight,
                requires_grad=self.weight.requires_grad,
                has_fp16_weights=False,
                # Note: After quantization, CB is the same as weight.
                CB=weight,
                SCB=scb,
            )
            self.bias = bias if bias is None else torch.nn.Parameter(bias)
        else:
            # We are loading a non-quantized state dict.

            # We could simply call the `super()._load_from_state_dict()` method here, but then we wouldn't be able to
            # load from a state_dict into a model on the "meta" device. Attempting to load into a model on the "meta"
            # device requires setting `assign=True`, doing this with the default `super()._load_from_state_dict()`
            # implementation causes `Params4Bit` to be replaced by a `torch.nn.Parameter`. By initializing a new
            # `Params4bit` object, we work around this issue. It's a bit hacky, but it gets the job done.
            self.weight = bnb.nn.Int8Params(
                data=weight,
                requires_grad=self.weight.requires_grad,
                has_fp16_weights=False,
                CB=None,
                SCB=None,
            )
            self.bias = bias if bias is None else torch.nn.Parameter(bias)


def _convert_linear_layers_to_llm_8bit(
    module: torch.nn.Module, ignore_modules: set[str], outlier_threshold: float, prefix: str = ""
) -> None:
    """Convert all linear layers in the module to bnb.nn.Linear8bitLt layers."""
    for name, child in module.named_children():
        fullname = f"{prefix}.{name}" if prefix else name
        if isinstance(child, torch.nn.Linear) and not any(fullname.startswith(s) for s in ignore_modules):
            has_bias = child.bias is not None
            replacement = InvokeLinear8bitLt(
                child.in_features,
                child.out_features,
                bias=has_bias,
                has_fp16_weights=False,
                threshold=outlier_threshold,
            )
            replacement.weight.data = child.weight.data
            if has_bias:
                replacement.bias.data = child.bias.data
            replacement.requires_grad_(False)
            module.__setattr__(name, replacement)
        else:
            _convert_linear_layers_to_llm_8bit(
                child, ignore_modules, outlier_threshold=outlier_threshold, prefix=fullname
            )


def get_parameter_device(parameter: torch.nn.Module):
    return next(parameter.parameters()).device


def quantize_model_llm_int8(model: torch.nn.Module, modules_to_not_convert: set[str], outlier_threshold: float = 6.0):
    """Apply bitsandbytes LLM.8bit() quantization to the model."""
    _convert_linear_layers_to_llm_8bit(
        module=model, ignore_modules=modules_to_not_convert, outlier_threshold=outlier_threshold
    )

    return model