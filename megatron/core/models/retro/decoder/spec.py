# Copyright (c) 2023, NVIDIA CORPORATION. All rights reserved.

# import abc
# import logging
# from typing import Literal, Optional, Union

# import torch
# from torch import Tensor

from megatron.core import parallel_state # , tensor_parallel
from megatron.core.models.gpt.gpt_decoder_spec import get_gpt_layer_spec
from megatron.core.transformer.attention import CrossAttentionSpec
from megatron.core.transformer.custom_layers.transformer_engine import (
    TEDotProductAttention,
    TELayerNormColumnParallelLinear,
    TERowParallelLinear,
)
from megatron.core.transformer.enums import AttnMaskType
from megatron.core.transformer.mlp import MLP
from megatron.core.models.retro.attn import BaseRetroCrossAttention
from megatron.core.models.retro.encoder import get_retro_encoder_block_spec
from megatron.core.transformer import (
    get_num_layers_to_build,
    ModuleSpec,
    TransformerBlockSpec,
    TransformerConfig,
    TransformerLayerSpec,
)

from .attn import (
    RetroDecoderBiasDropoutAdd,
    RetroDecoderCrossAttention,
    RetroDecoderLayerNorm,
)

# >>>
from lutil import pax
# <<<


def get_retro_decoder_layer_spec(encoder_block_spec=None) -> TransformerLayerSpec:
    spec = get_gpt_layer_spec()
    spec.cross_attention=CrossAttentionSpec(
        module=RetroDecoderCrossAttention,
        params={
            "attn_mask_type" : AttnMaskType.causal,
            "encoder_block_spec" : encoder_block_spec,
        },
        layernorm_linear_q=TELayerNormColumnParallelLinear,
        layernorm_linear_kv=TELayerNormColumnParallelLinear,
        core_attention=TEDotProductAttention,
        linear_proj=TERowParallelLinear,
    )
    # spec.cross_attn_bda=get_bias_dropout_add
    spec.cross_attn_bda=ModuleSpec(module=RetroDecoderBiasDropoutAdd)
    spec.post_cross_attn_layernorm=ModuleSpec(module=RetroDecoderLayerNorm)
    spec.ln_mlp=ModuleSpec(module=MLP)
    # pax("spec")
    return spec


def get_retro_decoder_block_spec(config: TransformerConfig) -> TransformerBlockSpec:

    # Num layers.
    assert parallel_state.get_pipeline_model_parallel_world_size() == 1
    assert parallel_state.get_virtual_pipeline_model_parallel_world_size() is None
    # num_layers = config.num_layers
    num_layers = get_num_layers_to_build(config)

    # Retro layer numbers.
    retro_layer_start = 6 if num_layers <= 15 else 9
    retro_layer_numbers = list(range(retro_layer_start, num_layers + 1, 3))

    # Layer specs.
    gpt_layer_spec = get_gpt_layer_spec()
    retro_layer_spec = get_retro_decoder_layer_spec()
    retro_layer_spec_with_retriever = \
        get_retro_decoder_layer_spec(get_retro_encoder_block_spec(config))

    # pax(
    #     "gpt_layer_spec",
    #     "retro_layer_spec",
    #     "retro_layer_spec_with_retriever",
    # )

    layer_specs = []
    for layer_number in range(1, num_layers + 1):
        if layer_number == retro_layer_numbers[0]:
            layer_specs.append(retro_layer_spec_with_retriever)
        elif layer_number in retro_layer_numbers:
            layer_specs.append(retro_layer_spec)
        else:
            layer_specs.append(gpt_layer_spec)

    # Block spec.
    block_spec = TransformerBlockSpec(layers=layer_specs)

    # pax({
    #     "config" : config,
    #     "num_layers" : num_layers,
    #     "retro_layer_numbers" : retro_layer_numbers,
    #     "layer_specs" : layer_specs,
    #     "attn specs" : [ s.cross_attention for s in layer_specs ],
    #     "block_spec" : [ L.cross_attention for L in block_spec.layers ],
    # })

    return block_spec


# @dataclass
# class RetroDecoderModelSpec:
#     gpt_layer_spec: TransformerLayerSpec = None
#     retro_decoder_with_retriever_layer_spec: TransformerLayerSpec = None
#     retro_decoder_layer_spec: TransformerLayerSpec = None

# def get_decoder_model_spec(encoder) -> RetroDecoderModelSpec:
#     spec = RetroDecoderModelSpec(
#         gpt_layer_spec = get_gpt_layer_spec(),
#         retro_decoder_with_retriever_layer_spec = get_decoder_layer_spec(encoder),
#         retro_decoder_layer_spec = get_decoder_layer_spec(None),
#     )
#     # pax("spec")
#     return spec
# def get_decoder_block_spec(config, pre_process, post_process) -> TransformerBlockSpec:
#     spec = TransformerBlockSpec(layers=get_decoder_layer_specs())
#     pax("spec")
#     return spec



# class RetroModel(MegatronModule, abc.ABC):
#     """Transformer language model.

#     Arguments:
#         config (TransformerConfig): transformer config

#         vocab_size (int): vocabulary size

#         max_sequence_length (int): maximum size of sequence. This is used for positional embedding

#         pre_process (bool): Include embedding layer (used with pipeline parallelism)
#         post_process (bool): Include an output layer (used with pipeline parallelism)

#         parallel_output (bool): Do not gather the outputs, keep them split across tensor parallel ranks

#         share_embeddings_and_output_weights (bool): When True, input embeddings and output logit weights are
#             shared. Defaults to False.

#         position_embedding_type (string): Position embedding type. Options ['learned_absolute', 'rope'].
#             Defaults is 'learned_absolute'.

#         rotary_percent (float): Percent of rotary dimension to use for rotary position embeddings.
#             Defaults to 1.0 (100%). Ignored unless position_embedding_type is 'rope'.

#         seq_len_interpolation_factor (float): scale of linearly interpolating RoPE for longer sequences.
#             The value must be a float larger than 1.0. Defaults to None.
#     """

#     def __init__(
#         self,
#         config: TransformerConfig,
#         spec: Union[RetroEncoderModelSpec, RetroDecoderModelSpec],
#         vocab_size: int,
#         max_sequence_length: int,
#         pre_process: bool = True,
#         post_process: bool = True,
#         fp16_lm_cross_entropy: bool = False,
#         parallel_output: bool = True,
#         share_embeddings_and_output_weights: bool = False,
#         position_embedding_type: Literal['learned_absolute', 'rope'] = 'learned_absolute',
#         rotary_percent: float = 1.0,
#         seq_len_interpolation_factor: Optional[float] = None,
#     ):
#         super().__init__(config=config)
#         # super().__init__(config=config, spec=spec)

#         # pax("config", "spec")

#         # >>>
#         # self.config: TransformerConfig = config
#         # <<<
#         self.spec = spec
#         self.vocab_size = vocab_size
#         self.max_sequence_length = max_sequence_length
#         self.pre_process = pre_process
#         self.post_process = post_process
#         self.fp16_lm_cross_entropy = fp16_lm_cross_entropy
#         self.parallel_output = parallel_output
#         self.share_embeddings_and_output_weights = share_embeddings_and_output_weights
#         self.position_embedding_type = position_embedding_type

#         # megatron core pipelining currently depends on model type
#         # TODO: remove this dependency ?
#         # >>>
#         # self.model_type = ModelType.encoder_or_decoder
#         # <<<

#         # Embeddings.
#         if self.pre_process:
#             self.embedding = GPTEmbedding(
#                 config=self.config,
#                 vocab_size=self.vocab_size,
#                 max_sequence_length=self.max_sequence_length,
#                 add_position_embedding=(self.position_embedding_type == 'learned_absolute'),
#             )

#         # Rotary Position Embeddings
#         if self.position_embedding_type == 'rope':
#             rotary_dim = self.config.kv_channels
#             if rotary_percent < 1.0:
#                 rotary_dim = int(rotary_dim * rotary_percent)

#             self.rotary_pos_emb = RotaryEmbedding(rotary_dim, seq_len_interpolation_factor)
#         else:
#             self.rotary_pos_emb = None

#         # Transformer.
#         # self.decoder = NewTransformerBlock(
#         #     config=self.config,
#         #     layer_specs=self.get_layer_specs(),
#         #     self_attn_mask_type=AttnMaskType.causal,
#         #     pre_process=self.pre_process,
#         #     post_process=self.post_process,
#         # )
#         self.decoder = RetroDecoderBlock(
#             config=config,
#             spec=spec,
#             pre_process=pre_process,
#             post_process=post_process,
#         )

#         # pax({"decoder": self.decoder})

#         # Output
#         if post_process:
#             self.output_layer = tensor_parallel.ColumnParallelLinear(
#                 config.hidden_size,
#                 self.vocab_size,
#                 config=config,
#                 init_method=config.init_method,
#                 bias=False,
#                 skip_bias_add=False,
#                 gather_output=not self.parallel_output,
#                 skip_weight_param_allocation=self.pre_process
#                 and self.share_embeddings_and_output_weights,
#             )

#         if self.share_embeddings_and_output_weights and (self.pre_process or self.post_process):
#             self.initialize_last_stage_with_word_embeddings()

#     def set_input_tensor(self, input_tensor):
#         """ See megatron.model.transformer.set_input_tensor()"""

#         # This is usually handled in schedules.py but some inference code still
#         # gives us non-lists or None
#         if not isinstance(input_tensor, list):
#             input_tensor = [input_tensor]

#         assert len(input_tensor) == 1, 'input_tensor should only be length 1 for gpt'
#         self.decoder.set_input_tensor(input_tensor[0])

#     def forward(
#         self,
#         input_ids: Tensor,
#         position_ids: Tensor,
#         attention_mask: Tensor,
#         decoder_input: Tensor = None,
#         labels: Tensor = None,
#         inference_params=None,
#         retriever_input_ids=None,
#         retriever_position_ids=None,
#         retriever_attn_mask=None,
#     ):
#         # If decoder_input is provided (not None), then input_ids and position_ids are ignored.
#         # Otherwise, apply embedding layer on input_ids and position_ids to get decoder_input.

#         # Decoder embedding.
#         if decoder_input is not None:
#             pass
#         elif self.pre_process:
#             decoder_input = self.embedding(input_ids=input_ids, position_ids=position_ids)
#         else:
#             # intermediate stage of pipeline
#             # decoder will get hidden_states from encoder.input_tensor
#             decoder_input = None

#         # Retriever embedding.
#         if retriever_input_ids is not None:
#             retriever_input = self.embedding(input_ids=retriever_input_ids,
#                                              position_ids=retriever_position_ids)
#             # pax("decoder_input", "retriever_input")
#         else:
#             retriever_input = None

#         # Rotary positional embeddings
#         rotary_pos_emb = None
#         if self.rotary_pos_emb is not None:
#             if inference_params is not None:
#                 rotary_seq_len = inference_params.max_sequence_length
#             else:
#                 if self.decoder.input_tensor is not None:
#                     rotary_seq_len = self.decoder.input_tensor.size(0)
#                 else:
#                     rotary_seq_len = decoder_input.size(0)

#                 # Decoder input is split along sequence dimension, but RoPE is applied in tensor parallel region
#                 if self.config.sequence_parallel:
#                     rotary_seq_len *= self.config.tensor_model_parallel_size

#             rotary_pos_emb = self.rotary_pos_emb(rotary_seq_len)

#         # Run decoder.
#         hidden_states = self.decoder(
#             hidden_states=decoder_input,
#             attention_mask=attention_mask,
#             inference_params=inference_params,
#             rotary_pos_emb=rotary_pos_emb,
#             retriever_input=retriever_input,
#             retriever_attn_mask=retriever_attn_mask,
#         )

#         if not self.post_process:
#             return hidden_states

#         # logits and loss
#         output_weight = None
#         if self.share_embeddings_and_output_weights:
#             output_weight = self.shared_embedding_or_output_weight()
#         logits, _ = self.output_layer(hidden_states, weight=output_weight)

#         if labels is None:
#             # [s b h] => [b s h]
#             return logits.transpose(0, 1).contiguous()

#         # [b s] => [s b]
#         labels = labels.transpose(0, 1).contiguous()
#         loss = tensor_parallel.vocab_parallel_cross_entropy(logits.float(), labels)

#         # [s b] => [b, s]
#         loss = loss.transpose(0, 1).contiguous()
#         return loss

#     def shared_embedding_or_output_weight(self):
#         if self.pre_process:
#             return self.embedding.word_embeddings.weight
#         elif self.post_process:
#             return self.output_layer.weight
#         return None

#     def initialize_last_stage_with_word_embeddings(self):

#         # This function just initializes the word embeddings in the final stage
#         # when we are using pipeline parallelism and sharing word
#         # embeddings. Nothing to do if we aren't sharing weights or aren't using
#         # pipeline parallelism.
#         if not self.share_embeddings_and_output_weights or (self.pre_process and self.post_process):
#             return

#         if self.post_process and not self.pre_process:
#             assert not parallel_state.is_pipeline_first_stage()
#             # set word_embeddings weights to 0 here, then copy first
#             # stage's weights using all_reduce below.
#             self.output_layer.weight.data.fill_(0)
#             self.output_layer.weight.shared = True

#         # Parameters are shared between the word embeddings layers, and the
#         # heads at the end of the model. In a pipelined setup with more than
#         # one stage, the initial embedding layer and the head are on different
#         # workers, so we do the following:
#         # 1. Create a second copy of word_embeddings on the last stage, with
#         #    initial parameters of 0.0.
#         # 2. Do an all-reduce between the first and last stage to ensure that
#         #    the two copies of word_embeddings start off with the same
#         #    parameter values.
#         # 3. In the training loop, before an all-reduce between the grads of
#         #    the two word_embeddings layers to ensure that every applied weight
#         #    update is the same on both stages.

#         # Ensure that first and last stages have the same initial parameter
#         # values.
#         if torch.distributed.is_initialized():
#             if parallel_state.is_rank_in_embedding_group():
#                 weight = self.shared_embedding_or_output_weight()
#                 torch.distributed.all_reduce(
#                     weight.data, group=parallel_state.get_embedding_group()
#                 )

#         elif not getattr(GPTModel, "embedding_warning_printed", False):
#             logging.getLogger(__name__).warning(
#                 "Distributed processes aren't initialized, so the output layer "
#                 "is not initialized with weights from the word embeddings. "
#                 "If you are just manipulating a model this is fine, but "
#                 "this needs to be handled manually. If you are training "
#                 "something is definitely wrong."
#             )
#             GPTModel.embedding_warning_printed = True

#     def sharded_state_dict(self, prefix=''):
#         sharded_state_dict = {}

#         if self.pre_process:
#             embedding_prefix = f'{prefix}embedding.'
#             embedding_sharded_state_dict = self.embedding.sharded_state_dict(
#                 prefix=embedding_prefix
#             )
#             sharded_state_dict.update(embedding_sharded_state_dict)

#         decoder_prefix = f'{prefix}decoder.'
#         decoder_sharded_state_dict = self.decoder.sharded_state_dict(prefix=decoder_prefix)
#         sharded_state_dict.update(decoder_sharded_state_dict)

#         if self.post_process:
#             output_layer_prefix = f'{prefix}output_layer.'
#             output_layer_key = f'{output_layer_prefix}weight'
#             if self.share_embeddings_and_output_weights:
#                 if not self.pre_process:
#                     # when sharing embeddings with last stage, we need to use the weights from the first stage
#                     # on pipeline first rank, word embeddings are saved to {prefix}embedding.word_embeddings.weight
#                     tensor = self.shared_embedding_or_output_weight()
#                     first_stage_word_emb_key = f'{prefix}embedding.word_embeddings.weight'
#                     dp_rank = parallel_state.get_data_parallel_rank()
#                     dp_size = parallel_state.get_data_parallel_world_size()
#                     last_stage_word_emb_replica_id = (
#                         dp_rank + dp_size
#                     )  # copy of first stage embedding

#                     sharded_output_layer_tensor = make_tp_sharded_tensor_for_checkpoint(
#                         tensor=tensor,
#                         key=first_stage_word_emb_key,
#                         replica_id=last_stage_word_emb_replica_id,
#                         allow_shape_mismatch=True,
#                     )

#                     sharded_state_dict[output_layer_key] = sharded_output_layer_tensor

#             else:
#                 output_layer_state_dict = self.output_layer.state_dict(
#                     prefix=output_layer_prefix, keep_vars=True
#                 )
#                 output_layer_tensor = output_layer_state_dict[output_layer_key]
#                 # independent output layer
#                 sharded_output_layer_tensor = make_tp_sharded_tensor_for_checkpoint(
#                     tensor=output_layer_tensor,
#                     key=output_layer_key,
#                     replica_id=parallel_state.get_data_parallel_rank(),
#                     allow_shape_mismatch=True,
#                 )

#                 sharded_state_dict[output_layer_key] = sharded_output_layer_tensor

#         return sharded_state_dict