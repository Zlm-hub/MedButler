from unsloth import FastLanguageModel, FastModel, FastVisionModel
from unsloth.trainer import UnslothVisionDataCollator
import torch
from trl import SFTTrainer, SFTConfig
from datasets import load_dataset
from unsloth import to_sharegpt
from unsloth import standardize_sharegpt
from unsloth import is_bfloat16_supported
from unsloth import apply_chat_template
from transformers import TrainingArguments
from transformers import TextStreamer
from torchao.quantization import quantize_
from torchao.quantization.qat import QATConfig

max_seq_length = 4096

model, processor = FastLanguageModel.from_pretrained(
    model_name = "/root/autodl-tmp/qwen35-4b",
    load_in_4bit = False,
    load_in_8bit = False,
    full_finetuning = False,
    use_gradient_checkpointing = True,
    local_files_only=True,
)

model = FastLanguageModel.get_peft_model(
   model,
   finetune_vision_layers     = True, # False if not finetuning vision layers
   finetune_language_layers   = True, # False if not finetuning language layers
   finetune_attention_modules = True, # False if not finetuning attention layers
   finetune_mlp_modules       = True, # False if not finetuning MLP layers
   r = 32,
   target_modules = ["q_proj", "k_proj", "v_proj", "o_proj","gate_proj", "up_proj", "down_proj",],
   lora_alpha = 32,
   lora_dropout = 0,
   bias = "none",
   random_state = 3407,
   use_rslora = False,
   loftq_config = None,
)

dataset = load_dataset(path="imagefolder", data_dir="./dataset-img-train")

instruction = "解读这个医学报告，一句话指出其中异常指标"

def convert_to_conversation(sample):
    conversation = [
        { "role": "user",
          "content" : [
            {"type" : "text",  "text"  : instruction},
            {"type" : "image", "image" : sample["image"]} ]
        },
        { "role" : "assistant",
          "content" : [
            {"type" : "text",  "text"  : sample["additional_feature"]} ]
        },
    ]
    return { "messages" : conversation }
pass

converted_dataset = [convert_to_conversation(sample) for sample in dataset["train"]]

FastVisionModel.for_training(model)

trainer = SFTTrainer(
    model = model,
    tokenizer = processor,
    data_collator = UnslothVisionDataCollator(model, processor),
    train_dataset = converted_dataset,
    dataset_text_field = "text",
    max_seq_length = max_seq_length,
    dataset_num_proc = 8,
    packing = False, # Can make training 5x faster for short sequences.
    args = SFTConfig(
        per_device_train_batch_size = 4,
        gradient_accumulation_steps = 4,
        warmup_steps = 5,
        # max_steps = 60,
        num_train_epochs = 3, # Set this instead of max_steps for full training runs
        learning_rate = 2e-4,
        logging_steps = 1,
        optim = "adamw_8bit",
        weight_decay = 0.001,
        lr_scheduler_type = "linear",
        seed = 3407,
        output_dir = "outputs",
        report_to = "none",     # For Weights and Biases

        # You MUST put the below items for vision finetuning:
        remove_unused_columns = False,
        dataset_text_field = "",
        dataset_kwargs = {"skip_prepare_dataset": True},
        max_length = 4096,
    ),
)

trainer_stats = trainer.train()

print("saving...")
model.save_pretrained_merged("/root/autodl-tmp/qwen35-4b-med-vl", processor)
print("saved")
