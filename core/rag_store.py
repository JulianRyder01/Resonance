# core/rag_store.py
import os
import chromadb
from chromadb.config import Settings
import uuid
import datetime

class RAGStore:
    """
    负责长期记忆的向量存储与检索 (Retrieval-Augmented Generation)
    使用 ChromaDB 本地存储。
    """
    def __init__(self, persistence_path="./logs/vector_store", collection_name="resonance_memory"):
        self.persistence_path = persistence_path
        self.collection_name = collection_name
        
        # 确保目录存在
        os.makedirs(self.persistence_path, exist_ok=True)
        
        # 初始化 ChromaDB Client
        try:
            self.client = chromadb.PersistentClient(path=self.persistence_path)
            
            # 获取或创建集合
            # 使用默认的 embedding model (all-MiniLM-L6-v2)
            self.collection = self.client.get_or_create_collection(name=self.collection_name)
            print(f"[System]: Vector Database loaded from {self.persistence_path}")
        except Exception as e:
            print(f"[Error]: Failed to initialize Vector Store: {e}")
            self.collection = None

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