# Copyright (c) 2024 Lincoln D. Stein and the InvokeAI Team
"""Implementation of model loader service."""

from typing import Optional, Type

from invokeai.app.invocations.baseinvocation import InvocationContext
from invokeai.app.services.config import InvokeAIAppConfig
from invokeai.app.services.invocation_processor.invocation_processor_common import CanceledException
from invokeai.backend.model_manager import AnyModel, AnyModelConfig, SubModelType
from invokeai.backend.model_manager.load import LoadedModel, ModelLoaderRegistry, ModelLoaderRegistryBase
from invokeai.backend.model_manager.load.convert_cache import ModelConvertCacheBase
from invokeai.backend.model_manager.load.model_cache.model_cache_base import ModelCacheBase
from invokeai.backend.util.logging import InvokeAILogger

from .model_load_base import ModelLoadServiceBase


class ModelLoadService(ModelLoadServiceBase):
    """Wrapper around ModelLoaderRegistry."""

    def __init__(
        self,
        app_config: InvokeAIAppConfig,
        ram_cache: ModelCacheBase[AnyModel],
        convert_cache: ModelConvertCacheBase,
        registry: Optional[Type[ModelLoaderRegistryBase]] = ModelLoaderRegistry,
    ):
        """Initialize the model load service."""
        logger = InvokeAILogger.get_logger(self.__class__.__name__)
        logger.setLevel(app_config.log_level.upper())
        self._logger = logger
        self._app_config = app_config
        self._ram_cache = ram_cache
        self._convert_cache = convert_cache
        self._registry = registry

    @property
    def ram_cache(self) -> ModelCacheBase[AnyModel]:
        """Return the RAM cache used by this loader."""
        return self._ram_cache

    @property
    def convert_cache(self) -> ModelConvertCacheBase:
        """Return the checkpoint convert cache used by this loader."""
        return self._convert_cache

    def load_model(
        self,
        model_config: AnyModelConfig,
        submodel_type: Optional[SubModelType] = None,
        context: Optional[InvocationContext] = None,
    ) -> LoadedModel:
        """
        Given a model's configuration, load it and return the LoadedModel object.

        :param model_config: Model configuration record (as returned by ModelRecordBase.get_model())
        :param submodel: For main (pipeline models), the submodel to fetch.
        :param context: Invocation context used for event reporting
        """
        if context:
            self._emit_load_event(
                context=context,
                model_config=model_config,
            )

        implementation, model_config, submodel_type = self._registry.get_implementation(model_config, submodel_type)  # type: ignore
        loaded_model: LoadedModel = implementation(
            app_config=self._app_config,
            logger=self._logger,
            ram_cache=self._ram_cache,
            convert_cache=self._convert_cache,
        ).load_model(model_config, submodel_type)

        if context:
            self._emit_load_event(
                context=context,
                model_config=model_config,
                loaded=True,
            )
        return loaded_model

    def _emit_load_event(
        self,
        context: InvocationContext,
        model_config: AnyModelConfig,
        loaded: Optional[bool] = False,
    ) -> None:
        if context.services.queue.is_canceled(context.graph_execution_state_id):
            raise CanceledException()

        if not loaded:
            context.services.events.emit_model_load_started(
                queue_id=context.queue_id,
                queue_item_id=context.queue_item_id,
                queue_batch_id=context.queue_batch_id,
                graph_execution_state_id=context.graph_execution_state_id,
                model_config=model_config,
            )
        else:
            context.services.events.emit_model_load_completed(
                queue_id=context.queue_id,
                queue_item_id=context.queue_item_id,
                queue_batch_id=context.queue_batch_id,
                graph_execution_state_id=context.graph_execution_state_id,
                model_config=model_config,
            )
