# core/rag_store.py
import os
import uuid
import datetime
import sys
import pandas as pd

class RAGStore:
    """
    负责长期记忆的向量存储与检索。
    [升级版]：支持访问统计（Access Counting）和全量导出，带鲁棒性修复。
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
        metadata['type'] = metadata.get('type', 'general') # 类型：general, user_fact, project, insight
        
        # [新增] 统计字段初始化
        metadata['access_count'] = 0
        metadata['last_accessed'] = metadata['timestamp']

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
        语义检索相关记忆 + [自动更新访问统计]
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
            
            # results 结构: {'ids': [['id1', 'id2']], 'documents': [['text1', 'text2']], 'metadatas': [[{...}, {...}]]}
            
            if results and results['ids'] and results['ids'][0]:
                hit_ids = results['ids'][0]
                hit_docs = results['documents'][0]
                
                # [新增] 异步/同步更新统计数据 (Access Counter)
                # 为了不拖慢检索速度，这里简单直接更新，生产环境可放入线程
                self._increment_stats(hit_ids, results['metadatas'][0])
                
                return hit_docs
            return []
        except Exception as e:
            print(f"[Error]: Memory search failed: {e}")
            return []

    def _increment_stats(self, ids, current_metadatas):
        """[内部方法] 更新被检索记忆的计数器"""
        try:
            new_metadatas = []
            for meta in current_metadatas:
                # 复制原有 metadata 防止引用问题
                new_meta = meta.copy()
                # 计数 +1
                current_count = int(new_meta.get('access_count', 0))
                new_meta['access_count'] = current_count + 1
                new_meta['last_accessed'] = datetime.datetime.now().isoformat()
                new_metadatas.append(new_meta)
            
            # ChromaDB update 需要传入 ids 和新的 metadatas
            self.collection.update(
                ids=ids,
                metadatas=new_metadatas
            )
        except Exception as e:
            # 统计更新失败不应阻碍主流程，静默失败即可
            # print(f"[Warning] Failed to update memory stats: {e}")
            pass

    # [新增] 删除记忆功能，供前端管理使用
    def delete_memory(self, memory_id):
        """根据 ID 删除特定记忆"""
        if not self.collection:
            return False
        try:
            self.collection.delete(ids=[memory_id])
            return True
        except Exception as e:
            print(f"[Error] Failed to delete memory {memory_id}: {e}")
            return False

    def get_all_memories_as_df(self):
        """
        [修改] 导出所有记忆为 Pandas DataFrame，并进行严格的数据清洗。
        确保没有任何 NaN、NaT 或复杂对象，以便 API 能完美序列化为 JSON。
        """
        if not self.collection:
            return pd.DataFrame()
            
        try:
            # 获取所有数据
            all_data = self.collection.get(include=['metadatas', 'documents', 'embeddings'])
            
            records = []
            ids = all_data['ids']
            docs = all_data['documents']
            metas = all_data['metadatas']
            
            for i, uid in enumerate(ids):
                # 如果 meta 是 None (极端情况)，给个空字典
                row = metas[i].copy() if metas[i] else {}
                row['id'] = uid
                row['content'] = docs[i]
                # 确保数值列存在
                if 'access_count' not in row: row['access_count'] = 0
                records.append(row)
                
            df = pd.DataFrame(records)
            
            if df.empty:
                return pd.DataFrame(columns=['type', 'content', 'access_count', 'timestamp', 'last_accessed', 'id'])

            # --- [核心修复] Schema 补全与清洗逻辑 ---
            
            # 1. 确保核心列存在
            required_cols = ['type', 'content', 'access_count', 'timestamp', 'last_accessed', 'id']
            for col in required_cols:
                if col not in df.columns:
                    df[col] = None

            # 2. 填充默认值
            df['type'] = df['type'].fillna('unknown').astype(str)
            df['content'] = df['content'].fillna('').astype(str)
            df['access_count'] = df['access_count'].fillna(0).astype(int)
            
            # 3. 处理时间：确保全部转为字符串 ISO 格式，避免 JSON 序列化失败
            now_iso = datetime.datetime.now().isoformat()
            
            def safe_iso(val):
                if not val or pd.isna(val):
                    return now_iso
                return str(val)

            df['timestamp'] = df['timestamp'].apply(safe_iso)
            df['last_accessed'] = df['last_accessed'].apply(safe_iso)
            
            # 4. 最终清洗：将所有剩余的 NaN 变为空字符串
            df = df.fillna("")
                
            return df
        except Exception as e:
            print(f"Error exporting dataframe: {e}")
            # 发生错误时返回空但结构正确的 DataFrame，防止 UI 报错
            return pd.DataFrame(columns=['type', 'content', 'access_count', 'timestamp', 'last_accessed', 'id'])

    def count(self):
        if self.collection:
            return self.collection.count()
        return 0