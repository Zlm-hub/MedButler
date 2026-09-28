
from evalscope import TaskConfig, run_task
from evalscope.constants import EvalType

task_cfg = TaskConfig(
    model='/root/autodl-tmp/qwen35-4b',
    api_url='http://127.0.0.1:8000/v1',
    api_key="EMPTY",
    eval_type=EvalType.SERVICE,
    datasets=['general_qa'],  # 数据格式，问答题格式固定为 'general_qa'
    dataset_args={
        'general_qa': {
            "local_path": "qa",  # 自定义数据集路径
            "subset_list": [
                # 评测数据集名称，上述 *.jsonl 中的 *，可配置多个子数据集
                "med-dataset-test"       
            ]
        }
    },
    limit=256,
)

run_task(task_cfg=task_cfg)