import os
import glob
import subprocess
from multiprocessing import Pool, Queue
import argparse

# 初始化全局端口变量（只在子进程中生效）
worker_port = None

def init_worker(port_queue: Queue):
    """子进程初始化时，从队列里领一个端口绑定"""
    global worker_port
    worker_port = port_queue.get()

# def process_patient(patient_dir: str):
#     """被子进程执行的任务"""
#     global worker_port
    
#     # 构建输出路径，比如存到 tmp/results/patient02.json
#     out_dir = "/data1/jianf/test/results_2"
#     os.makedirs(out_dir, exist_ok=True)
#     out_file = os.path.join(out_dir, f"{os.path.basename(patient_dir)}.json")
    
#     # 构造命令，调用你写好的 main.py
#     cmd = [
#         "python", "/data1/jianf/test/main.py",
#         "--patient_dir", patient_dir,
#         "--out", out_file
#     ]
    
#     # 【核心】：给这个子进程注入专属的环境变量
#     env = os.environ.copy()
#     env["OLLAMA_PORT"] = str(worker_port)

#     print(f"[Port:{worker_port}] 开始处理病人: {os.path.basename(patient_dir)}")
    
#     # 执行命令（屏蔽掉标准输出，防止终端刷屏太乱，如果想看可以把 stdout 改回 None）
#     result = subprocess.run(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    
#     if result.returncode != 0:
#         print(f"❌ [Port:{worker_port}] 处理失败: {patient_dir}\n错误信息: {result.stderr}")
#     else:
#         print(f"✅ [Port:{worker_port}] 处理完成: {os.path.basename(patient_dir)}")

def process_patient(patient_dir: str):
    """被子进程执行的任务"""
    global worker_port
    
    # 获取病人名称，比如 "林昌海00980907"
    patient_id = os.path.basename(patient_dir)
    
    # 1. 构建最终 JSON 的输出路径
    out_dir = "/data1/jianf/test/results_last"
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, f"{patient_id}.json")
    
    # ================= 【新增：检测结果是否已存在】 =================
    # 如果这个病人对应的 json 文件已经存在，说明之前成功跑完过，直接跳过
    if os.path.exists(out_file):
        print(f"⏩ [Port:{worker_port}] 结果已存在，跳过病人: {patient_id}")
        return
    # ==========================================================
    
    # 2. 为当前病人构建专属的 dump 文件夹
    dump_base_dir = "/data1/jianf/test/tmp/dumps"
    patient_dump_dir = os.path.join(dump_base_dir, patient_id)
    os.makedirs(patient_dump_dir, exist_ok=True)
    
    dump_blocks_out = os.path.join(patient_dump_dir, "all_blocks.txt")
    dump_contexts_dir = os.path.join(patient_dump_dir, "contexts")
    
    # 3. 构造命令，强行传入专属 dump 路径覆盖 main.py 的默认值
    cmd = [
        "python", "/data1/jianf/test/main.py",
        "--patient_dir", patient_dir,
        "--out", out_file,
        "--model", "qwen3:8b",             # 【高速底座】：填入你之前用得最快的常规模型名称
        "--ecmo_model", "qwen14b-structured:latest",    # 【重装专家】：填入你本地的 DeepSeek 模型名称
        "--dump_blocks_out", dump_blocks_out,
        "--dump_contexts_dir", dump_contexts_dir
    ]
    
    # 给这个子进程注入专属的端口环境变量
    env = os.environ.copy()
    env["OLLAMA_PORT"] = str(worker_port)

    print(f"▶️ [Port:{worker_port}] 开始处理病人: {patient_id}")
    
    # 执行命令
    result = subprocess.run(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    
    if result.returncode != 0:
        print(f"❌ [Port:{worker_port}] 处理失败: {patient_id}\n错误信息: {result.stderr}")
    else:
        print(f"✅ [Port:{worker_port}] 处理完成: {patient_id}")
def main():
    parser = argparse.ArgumentParser(description="多进程/多端口并行处理病人数据")
    parser.add_argument("--data_dir", type=str, default="/data1/jianf/test/data", help="存放所有病人文件夹的根目录")
    # 这里定义你要使用的端口列表
    parser.add_argument("--ports", type=str, nargs="+", default=["11434", "11435", "11436", "11437", "11438", "11439"], help="Ollama服务端口列表")
    args = parser.parse_args()

    # 扫描目录下所有的条目，只保留是文件夹的（过滤掉可能存在的隐藏文件或其他文本文件）
    patient_dirs = [
        os.path.join(args.data_dir, d)
        for d in os.listdir(args.data_dir)
        if os.path.isdir(os.path.join(args.data_dir, d))
    ]
    patient_dirs = sorted(patient_dirs)

    if not patient_dirs:
        print(f"在 {args.data_dir} 下没有找到任何病人文件夹。")
        return

    # 把端口放进线程安全的队列中
    port_queue = Queue()
    for p in args.ports:
        port_queue.put(p)

    # 启动进程池，进程数等于你提供的端口数
    with Pool(processes=len(args.ports), initializer=init_worker, initargs=(port_queue,)) as pool:
        pool.map(process_patient, patient_dirs)

    print("🎉 所有病人数据处理完毕！")

if __name__ == "__main__":
    main()