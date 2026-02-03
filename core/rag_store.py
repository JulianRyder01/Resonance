# core/rag_store.py
import os
import uuid
import datetime
import sys

class RAGStore:
    """
    负责长期记忆的向量存储与检索。
    重构：显式管理嵌入模型，防止 ChromaDB 内部误报。
    """
    def __init__(self, persistence_path="./logs/vector_store", collection_name="resonance_memory"):
        self.persistence_path = persistence_path
        self.collection_name = collection_name
        self.is_available = False
        self.embedding_function = None
        
        # 确保目录存在
        os.makedirs(self.persistence_path, exist_ok=True)
        
        # 初始化 ChromaDB Client
        try:
            # 1. 强制在最前面加载，确保它在当前进程中是活的
            import onnxruntime
            import chromadb
            from chromadb.utils import embedding_functions
            
            # 2. 显式创建嵌入函数
            # 我们直接使用用户测试通过的逻辑
            self.embedding_function = embedding_functions.DefaultEmbeddingFunction()
            
            # 3. 立即进行一次“冷启动”测试，确保它真的能跑
            # 如果这里不报错，说明这一轮初始化是铁证如山的成功
            self.embedding_function(["warmup"])

            # 4. 初始化客户端
            self.client = chromadb.PersistentClient(path=self.persistence_path)
            
            # 5. 获取集合时，显式传入我们已经验证成功的 embedding_function
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_function
            )
            
            self.is_available = True
            print(f"[System]: Vector Database (RAG) is Available.")
            
        except Exception as e:
            self.is_available = False
            self.collection = None
            # 只有在初次启动失败时静默，不干扰 UI
            print(f"[RAG Init Debug]: {str(e)}")

    def add_memory(self, text, metadata=None):
        """
        添加一条记忆到向量数据库
        :param text: 记忆文本内容
        :param metadata: 额外的元数据 (dict)
        """
        if not self.collection:
            return False

        if metadata is None:
            metadata = {}
        
        # 自动注入时间戳
        metadata['timestamp'] = datetime.datetime.now().isoformat()
        metadata['type'] = metadata.get('type', 'general')

        try:
            self.collection.add(
                documents=[text],
                metadatas=[metadata],
                ids=[str(uuid.uuid4())]
            )
            return True
        except Exception as e:
            print(f"[Error]: Failed to add memory: {e}")
            return False

    def search_memory(self, query_text, n_results=3):
        """
        语义检索相关记忆
        :param query_text: 用户的问题
        :param n_results: 返回几条结果
        :return: list of strings (记忆内容)
        """
        if not self.collection:
            return []

        try:
            results = self.collection.query(
                query_texts=[query_text],
                n_results=n_results
            )
            
            # results['documents'] 是一个 list of list
            if results and results['documents']:
                return results['documents'][0]
            return []
        except Exception as e:
            print(f"[Error]: Memory search failed: {e}")
            return []

    def count(self):
        if self.collection:
            return self.collection.count()
        return 0