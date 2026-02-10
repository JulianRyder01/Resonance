# backend/test_fix.py
import sys
import os

print(f"Python: {sys.executable}")

print("1. 尝试导入 numpy...")
try:
    import numpy
    print(f"✅ Numpy 导入成功，版本: {numpy.__version__}")
    if numpy.__version__.startswith("2"):
        print("❌ 警告：Numpy 版本仍为 2.x，这会导致 ONNX 崩溃！请执行降级命令。")
except Exception as e:
    print(f"❌ Numpy 导入失败: {e}")

print("\n2. 尝试导入 onnxruntime...")
try:
    import onnxruntime
    print(f"✅ onnxruntime 导入成功，版本: {onnxruntime.__version__}")
except ImportError as e:
    print(f"❌ onnxruntime 导入失败 (DLL 错误): {e}")
    print(">> 可能原因: 1. Numpy 版本冲突 (请降级到 1.26.4)  2. 缺少 Visual C++ Redistributable")
except Exception as e:
    print(f"❌ 其他错误: {e}")

print("\n3. 尝试 ChromaDB 嵌入测试...")
try:
    from chromadb.utils import embedding_functions
    ef = embedding_functions.DefaultEmbeddingFunction()
    vec = ef(["hello world"])
    print(f"✅ 向量生成成功！维度: {len(vec[0])}")
    print("\n🎉 恭喜！环境已修复，可以启动 Resonance 了！")
except Exception as e:
    print(f"❌ ChromaDB 嵌入失败: {e}")