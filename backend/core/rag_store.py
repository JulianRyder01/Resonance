# core/rag_store.py
import os
import uuid
import datetime
import sys
import pandas as pd
import logging
import traceback

# 配置日志
logger = logging.getLogger("RAGStore")

class RAGStore:
    """
    负责长期记忆的向量存储与检索。
    [修复版 v3]: 引入 Lazy Loading 和重试机制，解决启动时初始化失败导致全程不可用的问题。
    """
    def __init__(self, persistence_path="./logs/vector_store", collection_name="resonance_memory"):
        self.persistence_path = os.path.abspath(persistence_path)
        self.collection_name = collection_name
        self.embedding_function = None
        self.client = None
        self.collection = None
        
        # 确保目录存在
        if not os.path.exists(self.persistence_path):
            try:
                os.makedirs(self.persistence_path, exist_ok=True)
            except Exception as e:
                logger.error(f"Failed to create directory {self.persistence_path}: {e}")

        print(f"[RAG Init]: Target Path -> {self.persistence_path}")

        # 尝试初始化（如果失败不阻断程序，依靠后续的 Lazy Load）
        self._initialize_db()

    def _initialize_db(self):
        """
        核心初始化逻辑。
        分离出来是为了支持失败后的重试。
        """
        try:
            # 1. 导入依赖 (如果在 __init__ 外导入可能会导致某些环境下的 DLL 冲突)
            import chromadb
            from chromadb.utils import embedding_functions
            
            # 2. 准备嵌入函数
            if not self.embedding_function:
                self.embedding_function = embedding_functions.DefaultEmbeddingFunction()
                # 预热一次，确保 ONNX 库加载成功
                self.embedding_function(["warmup"])

            # 3. 初始化客户端
            if not self.client:
                self.client = chromadb.PersistentClient(path=self.persistence_path)
            
            # 4. 获取或创建集合
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_function
            )
            
            count = self.collection.count()
            print(f"[RAG System]: ✅ Successfully connected. Records: {count}")
            return True

        except Exception as e:
            print(f"\n{'!'*40}")
            print(f"[RAG CRITICAL ERROR]: Initialization Failed!")
            print(f"Path: {self.persistence_path}")
            print(f"Error: {str(e)}")
            # 打印堆栈以便排查（如 SQLite 锁定或 DLL 缺失）
            traceback.print_exc()
            print(f"{'!'*40}\n")
            
            self.collection = None
            return False

    def _ensure_connection(self):
        """
        [新增] 惰性连接检查器。
        在每次操作前调用，如果发现连接断了或没初始化，尝试重连。
        """
        if self.collection is not None:
            return True
        
        print("[RAG Info]: Connection lost or not initialized. Retrying connection...")
        return self._initialize_db()

    def add_memory(self, text, metadata=None):
        if not self._ensure_connection():
            return False

        if metadata is None:
            metadata = {}
        
        metadata['timestamp'] = datetime.datetime.now().isoformat()
        metadata['type'] = metadata.get('type', 'general')
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
            print(f"[RAG Error] Add failed: {e}")
            return False

    def search_memory(self, query_text, n_results=3, strategy="semantic"):
        if not self._ensure_connection():
            return []

        try:
            # 保证 n_results 不超过总数
            count = self.collection.count()
            if count == 0: return []
            k = min(n_results, count)

            if strategy == "hybrid_time":
                return self._search_hybrid_time(query_text, k)
            else:
                return self._search_semantic(query_text, k)
        except Exception as e:
            print(f"[RAG Error] Search failed: {e}")
            return []

    def _search_semantic(self, query_text, n_results):
        results = self.collection.query(
            query_texts=[query_text],
            n_results=n_results
        )
        if results and results['ids'] and results['ids'][0]:
            # 异步更新统计，不阻塞查询
            try:
                self._increment_stats(results['ids'][0], results['metadatas'][0])
            except: pass
            return results['documents'][0]
        return []

    def _search_hybrid_time(self, query_text, n_results):
        # 获取更多候选项
        candidates_k = min(n_results * 3, self.collection.count())
        results = self.collection.query(
            query_texts=[query_text],
            n_results=candidates_k,
            include=['documents', 'metadatas', 'distances']
        )

        if not results or not results['ids'] or not results['ids'][0]:
            return []

        ids = results['ids'][0]
        docs = results['documents'][0]
        metas = results['metadatas'][0]
        dists = results['distances'][0]

        scored = []
        now = datetime.datetime.now()

        for i in range(len(ids)):
            # 语义分 (Distance -> Similarity)
            semantic_score = 1.0 / (1.0 + dists[i])
            
            # 时间分
            time_score = 0.5
            if metas[i].get('timestamp'):
                try:
                    dt = datetime.datetime.fromisoformat(metas[i]['timestamp'])
                    days = (now - dt).days
                    time_score = 1.0 / (1.0 + 0.1 * days)
                except: pass
            
            final_score = (semantic_score * 0.7) + (time_score * 0.3)
            scored.append({'doc': docs[i], 'score': final_score, 'id': ids[i], 'meta': metas[i]})

        scored.sort(key=lambda x: x['score'], reverse=True)
        top = scored[:n_results]
        
        # 更新统计
        try:
            self._increment_stats([x['id'] for x in top], [x['meta'] for x in top])
        except: pass

        return [x['doc'] for x in top]

    def _increment_stats(self, ids, metadatas):
        new_metas = []
        for meta in metadatas:
            m = meta.copy()
            m['access_count'] = int(m.get('access_count', 0)) + 1
            m['last_accessed'] = datetime.datetime.now().isoformat()
            new_metas.append(m)
        self.collection.update(ids=ids, metadatas=new_metas)

    def delete_memory(self, memory_id):
        if not self._ensure_connection(): return False
        try:
            self.collection.delete(ids=[memory_id])
            return True
        except Exception as e:
            print(f"[RAG Error] Delete failed: {e}")
            return False

    def get_all_memories_as_df(self):
        """
        导出所有记忆，带自动重连和容错处理。
        """
        # 1. 尝试连接
        if not self._ensure_connection():
            # 再次失败，返回空 DF 防止前端崩溃
            print("[RAG Warning]: Could not connect to DB for exporting.")
            return pd.DataFrame(columns=['type', 'content', 'access_count', 'timestamp', 'last_accessed', 'id'])

        try:
            count = self.collection.count()
            if count == 0:
                return pd.DataFrame(columns=['type', 'content', 'access_count', 'timestamp', 'last_accessed', 'id'])

            # 2. 获取数据
            all_data = self.collection.get(
                limit=count,
                include=['metadatas', 'documents']
            )

            records = []
            ids = all_data['ids']
            docs = all_data['documents']
            metas = all_data['metadatas']

            for i, uid in enumerate(ids):
                item = metas[i] if metas[i] else {}
                # 创建副本，防止修改原始引用
                row = item.copy()
                row['id'] = uid
                row['content'] = docs[i] if docs[i] else ""
                records.append(row)

            df = pd.DataFrame(records)

            # 3. 数据清洗 (Schema Enforcement)
            required_cols = ['type', 'content', 'access_count', 'timestamp', 'last_accessed', 'id']
            for col in required_cols:
                if col not in df.columns:
                    if col == 'access_count': df[col] = 0
                    elif col == 'content': df[col] = ""
                    else: df[col] = "unknown"

            # 填充 NaN
            df['type'] = df['type'].fillna('unknown').astype(str)
            df['content'] = df['content'].fillna('').astype(str)
            df['access_count'] = df['access_count'].fillna(0).astype(int)

            now_iso = datetime.datetime.now().isoformat()
            def clean_time(val):
                if pd.isna(val) or str(val).strip() == "": return now_iso
                return str(val)

            df['timestamp'] = df['timestamp'].apply(clean_time)
            df['last_accessed'] = df['last_accessed'].apply(clean_time)
            
            df = df.fillna("") # 兜底清洗

            return df

        except Exception as e:
            print(f"[RAG Error] DataFrame Export Failed: {e}")
            traceback.print_exc()
            return pd.DataFrame(columns=['type', 'content', 'access_count', 'timestamp', 'last_accessed', 'id'])

    def count(self):
        if self._ensure_connection():
            return self.collection.count()
        return 0