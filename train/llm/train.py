from unsloth import FastLanguageModel, FastModel
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
tokenizer = processor.tokenizer

model = FastLanguageModel.get_peft_model(
   model,
   finetune_vision_layers     = False, # False if not finetuning vision layers
   finetune_language_layers   = True, # False if not finetuning language layers
   finetune_attention_modules = True, # False if not finetuning attention layers
   finetune_mlp_modules       = True, # False if not finetuning MLP layers
   r = 32,
   target_modules = ["q_proj", "k_proj", "v_proj", "o_proj","gate_proj", "up_proj", "down_proj",],
   lora_alpha = 32,
   lora_dropout = 0,
   bias = "none",
   use_gradient_checkpointing = True,
   random_state = 3407,
   use_rslora = False,
   loftq_config = None,
)

dataset = load_dataset('json', data_files='../2-prepare-dataset/med-dataset-train.jsonl', split='train')
system_prompt = "你是一个专业的医疗健康顾问，能够提供有关体检指标异常的专业健康建议。"

dataset = to_sharegpt(
    dataset,
    merged_prompt = f"{system_prompt}\n\n{{query}}",
    output_column_name = "response",
)

dataset = standardize_sharegpt(dataset)
dataset = apply_chat_template(
    dataset,
    tokenizer=tokenizer,
)
print(dataset[0])

trainer = SFTTrainer(
    model = model,
    tokenizer = tokenizer,
    train_dataset = dataset,
    dataset_text_field = "text",
    max_seq_length = max_seq_length,
    dataset_num_proc = 8,
    packing = False, # Can make training 5x faster for short sequences.
    args = TrainingArguments(
        per_device_train_batch_size = 2,
        gradient_accumulation_steps = 8,
        warmup_steps = 5,
        max_steps = 3000,
        # num_train_epochs = 1, # For longer training runs!
        learning_rate = 5e-4,
        fp16 = not is_bfloat16_supported(),
        bf16 = is_bfloat16_supported(),
        logging_steps = 2,
        optim = "adamw_8bit",
        weight_decay = 0.01,
        lr_scheduler_type = "linear",
        seed = 3407,
        output_dir = "outputs",
        report_to = "none", # Use this for WandB etc
    ),
)

trainer_stats = trainer.train()

FastLanguageModel.for_inference(model) # Enable native 2x faster inference

messages = [                   
    {"role": "user", "content": "我肚子疼"},
]
input_ids = tokenizer.apply_chat_template(
    messages,
    add_generation_prompt = True,
    return_tensors = "pt",
).to("cuda")

text_streamer = TextStreamer(tokenizer, skip_prompt = True)
_ = model.generate(input_ids, streamer = text_streamer, max_new_tokens = 1024, pad_token_id = tokenizer.eos_token_id)

print("saving...")
model.save_pretrained_merged("/root/autodl-tmp/qwen35-4b-med-llm", tokenizer)
#tokenizer.save_pretrained("/root/autodl-tmp/qwen35-08b-finetuned-ffmpeglog")
print("saved")
