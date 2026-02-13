# backend/core/rag_store.py
import os
import uuid
import datetime
import sys
import pandas as pd
import logging
import traceback
import math
import re
from collections import Counter
from typing import List, Dict, Any

# 配置日志
logger = logging.getLogger("RAGStore")

# --- [新增] BM25 算法实现 ---
class BM25:
    def __init__(self, corpus: List[str], k1=1.5, b=0.75):
        """
        BM25算法的构造器
        :param corpus: 文档字符串列表
        :param k1: BM25算法中的调节参数k1
        :param b: BM25算法中的调节参数b
        """
        self.k1 = k1
        self.b = b
        self.corpus_size = len(corpus)
        self.avgdl = 0
        self.doc_freqs = []
        self.idf = {}
        self.doc_len = []
        
        # 预处理文档
        tokenized_corpus = [self.tokenize(doc) for doc in corpus]
        self._initialize(tokenized_corpus)

    def tokenize(self, text: str) -> List[str]:
        """
        简单的混合分词器 (支持中文和英文)
        生产环境建议替换为 jieba (中文) + split (英文)
        """
        if not text:
            return []
        # 将文本转小写，匹配连续的字母数字作为单词，或者匹配单个的中文字符
        # 这是一个简化的正则，能够同时处理 "Hello world" 和 "你好世界"
        tokens = re.findall(r'(?u)\b\w+\b|[\u4e00-\u9fa5]', text.lower())
        return tokens

    def _initialize(self, docs):
        """
        初始化方法，计算所有词的逆文档频率
        """
        self.doc_len = [len(doc) for doc in docs]
        self.avgdl = sum(self.doc_len) / self.corpus_size if self.corpus_size > 0 else 0
        
        df = {}  # 用于存储每个词在多少不同文档中出现
        
        for doc in docs:
            # 为每个文档创建一个词频统计
            self.doc_freqs.append(Counter(doc))
            # 更新df值
            for word in set(doc):
                df[word] = df.get(word, 0) + 1
        
        # 计算每个词的IDF值
        for word, freq in df.items():
            self.idf[word] = math.log((self.corpus_size - freq + 0.5) / (freq + 0.5) + 1)

    def score(self, doc_idx, query_tokens):
        """
        计算文档与查询的BM25得分
        """
        score = 0.0
        doc_freq = self.doc_freqs[doc_idx]
        doc_len = self.doc_len[doc_idx]
        
        for word in query_tokens:
            if word in doc_freq:
                freq = doc_freq[word]
                # 应用BM25计算公式
                numerator = self.idf[word] * freq * (self.k1 + 1)
                denominator = freq + self.k1 * (1 - self.b + self.b * doc_len / (self.avgdl + 1e-6))
                score += numerator / denominator
        return score

    def search(self, query: str, top_k=5):
        """
        搜索入口
        :return: List of (doc_index, score) sorted by score desc
        """
        tokens = self.tokenize(query)
        scores = []
        for i in range(self.corpus_size):
            s = self.score(i, tokens)
            if s > 0:
                scores.append((i, s))
        
        # 按分数降序排列
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

# --- RAG Store 主类 ---

class RAGStore:
    """
    负责长期记忆的向量存储与检索。
    [升级]: 集成 Semantic + BM25 混合检索 (70/30)
    """
    def __init__(self, persistence_path="./logs/vector_store", collection_name="resonance_memory"):
        self.persistence_path = os.path.abspath(persistence_path)
        self.collection_name = collection_name
        self.embedding_function = None
        self.client = None
        self.collection = None
        
        # [新增] 内存中的 BM25 索引缓存
        self.bm25_index = None
        self.memory_docs_cache = [] # 存储 (id, text, metadata) 的列表，与 BM25 索引对应
        
        # 确保目录存在
        if not os.path.exists(self.persistence_path):
            try:
                os.makedirs(self.persistence_path, exist_ok=True)
            except Exception as e:
                logger.error(f"Failed to create directory {self.persistence_path}: {e}")

        print(f"[RAG Init]: Target Path -> {self.persistence_path}")

        # 尝试初始化
        self._initialize_db()

    def _initialize_db(self):
        """
        核心初始化逻辑，连接 ChromaDB 并构建内存 BM25 索引
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
            
            # [新增] 5. 构建 BM25 索引 (加载所有数据)
            self._rebuild_bm25_index()
            
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

    def _rebuild_bm25_index(self):
        """
        [新增] 从 ChromaDB 拉取所有数据并重建 BM25 索引
        注意：数据量极大时需优化，此处适用于一般个人 Agent 规模 (<10w 条)
        """
        try:
            if not self.collection: return
            
            count = self.collection.count()
            if count == 0:
                self.bm25_index = None
                self.memory_docs_cache = []
                return

            # 拉取所有数据
            all_data = self.collection.get()
            ids = all_data['ids']
            documents = all_data['documents']
            metadatas = all_data['metadatas']
            
            self.memory_docs_cache = []
            corpus = []
            
            for i, doc_id in enumerate(ids):
                text = documents[i] if documents[i] else ""
                self.memory_docs_cache.append({
                    "id": doc_id,
                    "document": text,
                    "metadata": metadatas[i]
                })
                corpus.append(text)
            
            # 初始化 BM25
            self.bm25_index = BM25(corpus)
            # print(f"[RAG System]: BM25 Index rebuilt with {len(corpus)} documents.")
            
        except Exception as e:
            print(f"[RAG Error] Failed to rebuild BM25 index: {e}")

    def _ensure_connection(self):
        """
        [新增] 惰性连接检查器。
        在每次操作前调用，如果发现连接断了或没初始化，尝试重连。
        """
        if self.collection is not None:
            return True
        
        print("[RAG Info]: Connection lost or not initialized. Retrying connection...")
        return self._initialize_db()

    # --- [修改点 - 需求②] 新增相似度计算方法 ---
    def calculate_similarity(self, text: str) -> float:
        """
        计算输入文本与库中现有记忆的最大相似度。
        策略：70% Semantic Score + 30% BM25 Score (Normalized)
        返回：0.0 ~ 1.0 的相似度得分
        """
        if not self._ensure_connection():
            return 0.0
        
        count = self.collection.count()
        if count == 0:
            return 0.0

        # 1. Semantic Search
        try:
            sem_results = self.collection.query(
                query_texts=[text],
                n_results=1, # 只需要最相似的那一个
                include=['distances']
            )
            sem_dist = sem_results['distances'][0][0] if sem_results['distances'] else 100.0
            # Convert Distance to Similarity (0~1)
            # Chroma L2 distance can be > 1, so simple 1/(1+d) is safe
            sem_score = 1.0 / (1.0 + sem_dist)
        except Exception:
            sem_score = 0.0

        # 2. BM25 Search
        bm25_score = 0.0
        if self.bm25_index:
            scores = self.bm25_index.search(text, top_k=1)
            if scores:
                raw_score = scores[0][1]
                # BM25 score is unbound, need rough normalization. 
                # Assuming simple scaling based on query length approx.
                # Here we simplify: if raw_score > 10 it's very high.
                # A better approach is MinMax scaling if we had batch scores, 
                # but for single query check, we use a heuristic sigmoid or cap.
                # Let's use a logistic function to squash 0~inf to 0~1
                bm25_score = 1.0 / (1.0 + math.exp(-0.5 * (raw_score - 5))) 

        # 3. Weighted Sum
        final_score = (0.7 * sem_score) + (0.3 * bm25_score)
        
        # print(f"[RAG Dedup Check] Text: '{text[:20]}...' | Sem: {sem_score:.3f} | BM25: {bm25_score:.3f} | Final: {final_score:.3f}")
        return final_score

    def add_memory(self, text, metadata=None):
        if not self._ensure_connection():
            return False

        if metadata is None:
            metadata = {}
        
        # 确保时间戳
        metadata['timestamp'] = datetime.datetime.now().isoformat()
        # [修改] 允许传入 AI 标签，如果没有则默认为 general
        metadata['type'] = metadata.get('type', 'general') 
        metadata['access_count'] = 0
        metadata['last_accessed'] = metadata['timestamp']

        try:
            self.collection.add(
                documents=[text],
                metadatas=[metadata],
                ids=[str(uuid.uuid4())]
            )
            # [新增] 插入数据后，简单的做法是重建索引 (或者可以优化为增量更新)
            # 为了数据一致性，这里选择重建（假设写入频率远低于读取）
            self._rebuild_bm25_index()
            return True
        except Exception as e:
            print(f"[RAG Error] Add failed: {e}")
            return False

    def search_memory(self, query_text, n_results=3, strategy="hybrid_bm25"):
        """
        检索入口
        :param strategy: 'semantic', 'hybrid_time', 'hybrid_bm25' (default)
        """
        if not self._ensure_connection():
            return []

        try:
            # 保证 n_results 不超过总数
            count = self.collection.count()
            if count == 0: return []
            
            # 确保获取足够多的候选集以便重排序
            k = min(n_results, count)

            if strategy == "hybrid_bm25":
                return self._search_hybrid_bm25(query_text, k)
            elif strategy == "hybrid_time":
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
        """语义 + 时间衰减"""
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
        
        try:
            self._increment_stats([x['id'] for x in top], [x['meta'] for x in top])
        except: pass

        return [x['doc'] for x in top]

    def _search_hybrid_bm25(self, query_text, n_results):
        """
        [新增] 语义 70% + BM25 30% 混合检索
        """
        # 1. 语义检索 (获取较多候选项，例如 n * 4)
        top_k_candidates = min(n_results * 4, self.collection.count())
        
        # Semantic Search
        sem_results = self.collection.query(
            query_texts=[query_text],
            n_results=top_k_candidates,
            include=['documents', 'metadatas', 'distances']
        )
        
        # 2. BM25 检索 (在全量内存索引中检索)
        bm25_results_list = []
        if self.bm25_index:
            bm25_results_list = self.bm25_index.search(query_text, top_k=top_k_candidates)
        
        # --- 融合逻辑 (Normalization + Weighted Sum) ---
        
        # 建立 ID -> {sem_score, bm25_score, content, metadata} 的映射
        candidates = {}
        
        # 处理语义结果
        sem_max_score = 0.0
        if sem_results and sem_results['ids'] and sem_results['ids'][0]:
            ids = sem_results['ids'][0]
            docs = sem_results['documents'][0]
            metas = sem_results['metadatas'][0]
            dists = sem_results['distances'][0]
            
            for i, doc_id in enumerate(ids):
                # Distance to Similarity: 1 / (1 + distance)
                sim = 1.0 / (1.0 + dists[i])
                sem_max_score = max(sem_max_score, sim)
                candidates[doc_id] = {
                    "doc": docs[i],
                    "meta": metas[i],
                    "sem_score": sim,
                    "bm25_score": 0.0
                }
        
        # 处理 BM25 结果
        bm25_max_score = 0.0
        if bm25_results_list:
            bm25_max_score = bm25_results_list[0][1] # Sorted desc
            for idx, score in bm25_results_list:
                # 从 cache 找回文档信息
                if idx < len(self.memory_docs_cache):
                    cached_item = self.memory_docs_cache[idx]
                    doc_id = cached_item['id']
                    
                    if doc_id not in candidates:
                        candidates[doc_id] = {
                            "doc": cached_item['document'],
                            "meta": cached_item['metadata'],
                            "sem_score": 0.0,
                            "bm25_score": score
                        }
                    else:
                        candidates[doc_id]["bm25_score"] = score

        # 归一化并加权
        # 权重: Semantic 0.7, BM25 0.3
        final_scores = []
        for doc_id, data in candidates.items():
            # Min-Max Normalization (Simple)
            norm_sem = data["sem_score"] / sem_max_score if sem_max_score > 0 else 0
            norm_bm25 = data["bm25_score"] / bm25_max_score if bm25_max_score > 0 else 0
            
            weighted_score = (0.7 * norm_sem) + (0.3 * norm_bm25)
            
            final_scores.append({
                "id": doc_id,
                "doc": data["doc"],
                "meta": data["meta"],
                "score": weighted_score
            })
            
        # 排序
        final_scores.sort(key=lambda x: x['score'], reverse=True)
        top = final_scores[:n_results]
        
        # 更新访问统计
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
            # 删除后重建索引以保持一致
            self._rebuild_bm25_index()
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