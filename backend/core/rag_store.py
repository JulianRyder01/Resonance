# core/rag_store.py
import os
import uuid
import datetime
import sys
import pandas as pd
import numpy as np # [新增] 用于向量计算

class RAGStore:
    """
    负责长期记忆的向量存储与检索。
    [升级版]：支持多套检索策略 (Semantic / Hybrid-Time)，修复了数据导出为空的问题。
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

    # [新增] 支持策略选择的搜索接口
    def search_memory(self, query_text, n_results=3, strategy="semantic"):
        """
        根据策略检索相关记忆
        :param strategy: 'semantic' (默认) 或 'hybrid_time' (时间加权)
        """
        if not self.collection:
            return []

        try:
            if strategy == "hybrid_time":
                return self._search_hybrid_time(query_text, n_results)
            else:
                return self._search_semantic(query_text, n_results)
        except Exception as e:
            print(f"[Error]: Memory search failed ({strategy}): {e}")
            return []

    # [原有] 纯语义检索
    def _search_semantic(self, query_text, n_results):
        results = self.collection.query(
            query_texts=[query_text],
            n_results=n_results
        )
        
        if results and results['ids'] and results['ids'][0]:
            hit_ids = results['ids'][0]
            hit_docs = results['documents'][0]
            
            # 更新统计
            self._increment_stats(hit_ids, results['metadatas'][0])
            
            return hit_docs
        return []

    # [新增] 混合检索策略：语义相似度 + 时间衰减因子
    def _search_hybrid_time(self, query_text, n_results):
        """
        第二套 RAG 策略：不仅仅看语义距离，还偏向于最近的记忆。
        Score = (1 - Cosine_Distance) * 0.7 + (Time_Decay_Factor) * 0.3
        """
        # 1. 获取更多候选集 (例如取 3 倍数量)
        candidates_k = n_results * 3
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
        dists = results['distances'][0] # Chroma 默认是 L2 或 Cosine distance，越小越相似

        # 2. 计算混合分数
        scored_candidates = []
        now = datetime.datetime.now()

        for i in range(len(ids)):
            # A. 语义分 (将 distance 转化为相似度 0~1)
            # 假设 distance 是 cosine distance (0~2)，我们需要反转它
            semantic_score = 1.0 / (1.0 + dists[i]) 

            # B. 时间分 (Time Decay)
            ts_str = metas[i].get('timestamp')
            time_score = 0.0
            if ts_str:
                try:
                    dt = datetime.datetime.fromisoformat(ts_str)
                    delta_days = (now - dt).days
                    # 衰减公式：1 / (1 + 0.1 * 天数) -> 刚创建=1.0, 10天后=0.5
                    time_score = 1.0 / (1.0 + 0.1 * delta_days)
                except:
                    time_score = 0.5 # 解析失败给个中间值

            # C. 混合加权 (语义 70%, 时间 30%)
            final_score = (semantic_score * 0.7) + (time_score * 0.3)
            
            scored_candidates.append({
                "doc": docs[i],
                "id": ids[i],
                "meta": metas[i],
                "score": final_score
            })

        # 3. 按最终分数排序并截断
        scored_candidates.sort(key=lambda x: x['score'], reverse=True)
        top_hits = scored_candidates[:n_results]

        # 4. 更新统计 (只更新最终选中的)
        hit_ids = [x['id'] for x in top_hits]
        hit_metas = [x['meta'] for x in top_hits]
        self._increment_stats(hit_ids, hit_metas)

        return [x['doc'] for x in top_hits]

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
        [修复] 导出所有记忆为 Pandas DataFrame，并进行严格的数据清洗。
        确保没有任何 NaN、NaT 或复杂对象，防止前端显示为空。
        """
        if not self.collection:
            return pd.DataFrame()
            
        try:
            # 获取所有数据
            all_data = self.collection.get(include=['metadatas', 'documents'])
            
            records = []
            ids = all_data['ids']
            docs = all_data['documents']
            metas = all_data['metadatas']
            
            for i, uid in enumerate(ids):
                # 必须创建一个新字典，防止引用污染
                row = metas[i].copy() if metas[i] else {}
                row['id'] = uid
                row['content'] = docs[i]
                
                # 确保数值列存在且为 int
                try:
                    row['access_count'] = int(row.get('access_count', 0))
                except:
                    row['access_count'] = 0
                    
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
            
            def clean_time(val):
                if pd.isna(val) or val is None or str(val).strip() == "":
                    return now_iso
                return str(val)

            df['timestamp'] = df['timestamp'].apply(clean_time)
            df['last_accessed'] = df['last_accessed'].apply(clean_time)
            
            return df
        except Exception as e:
            print(f"Error exporting dataframe: {e}")
            # 发生错误时返回空但结构正确的 DataFrame，防止 UI 报错
            return pd.DataFrame(columns=['type', 'content', 'access_count', 'timestamp', 'last_accessed', 'id'])

    def count(self):
        if self.collection:
            return self.collection.count()
        return 0