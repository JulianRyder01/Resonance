import sys
import os

def test_onnx_and_chroma():
    print("--- 1. 环境检查 ---")
    print(f"Python 版本: {sys.version}")
    print(f"当前路径: {os.getcwd()}")
    
    print("\n--- 2. 尝试直接导入 onnxruntime ---")
    try:
        import onnxruntime
        print(f"✅ onnxruntime 导入成功！版本: {onnxruntime.__version__}")
        print(f"可用的加速提供者: {onnxruntime.get_available_providers()}")
    except Exception as e:
        print(f"❌ onnxruntime 导入失败: {e}")
        return

    print("\n--- 3. 尝试初始化 ChromaDB 默认嵌入模型 ---")
    try:
        from chromadb.utils import embedding_functions
        default_ef = embedding_functions.DefaultEmbeddingFunction()
        
        # 这里的测试会真正触发 DLL 初始化
        test_text = ["Hello, Resonance!"]
        print("正在进行模拟向量计算（这会加载 DLL）...")
        embeddings = default_ef(test_text)
        
        print(f"✅ 向量计算成功！得到维度: {len(embeddings[0])}")
    except Exception as e:
        print(f"❌ 向量计算失败 (DLL 初始化报错通常发生在这里): \n{e}")

if __name__ == "__main__":
    test_onnx_and_chroma()