# core/functools/web_engine.py
import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
import logging
import re

class WebEngine:
    """
    负责处理联网搜索和网页内容提取的核心引擎。
    不依赖 Selenium，更加轻量稳定。
    """
    
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        }

    def search(self, query, max_results=5):
        """
        使用 DuckDuckGo 进行搜索，无需 API Key。
        返回结果列表: [{'title':..., 'href':..., 'body':...}]
        """
        results = []
        try:
            with DDGS() as ddgs:
                # 使用 text 搜索
                ddgs_gen = ddgs.text(query, max_results=max_results)
                for r in ddgs_gen:
                    results.append({
                        "title": r.get('title'),
                        "url": r.get('href'),
                        "snippet": r.get('body')
                    })
            return results
        except Exception as e:
            return [{"error": f"Search failed: {str(e)}"}]

    def fetch_page(self, url):
        """
        获取网页内容并提取正文（去除广告、导航栏、脚本）。
        """
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            
            # 自动处理编码
            if response.encoding == 'ISO-8859-1':
                response.encoding = response.apparent_encoding
                
            soup = BeautifulSoup(response.text, 'lxml')
            
            # 1. 移除无关元素
            for script in soup(["script", "style", "nav", "footer", "header", "iframe", "noscript"]):
                script.decompose()

            # 2. 提取标题
            title = soup.title.string if soup.title else "No Title"
            
            # 3. 提取正文 (简单算法：提取 p, h1-h6, li)
            # 也可以使用 readability-lxml 库，这里手写一个轻量级的
            text_blocks = []
            
            # 优先获取 article 标签
            article = soup.find('article')
            target_dom = article if article else soup.body
            
            if target_dom:
                for element in target_dom.find_all(['p', 'h1', 'h2', 'h3', 'ul', 'ol', 'div']):
                    text = element.get_text(strip=True)
                    # 过滤过短的文本（通常是菜单项）
                    if len(text) > 20 or element.name in ['h1', 'h2', 'h3']:
                        text_blocks.append(text)
            
            # 合并文本，限制长度防止 Context 溢出
            full_text = "\n\n".join(text_blocks)
            if len(full_text) > 8000:
                full_text = full_text[:8000] + "\n...[Content Truncated]"
                
            return {
                "title": title,
                "url": url,
                "content": full_text if full_text else "No textual content found."
            }
            
        except Exception as e:
            return {"error": f"Failed to fetch page: {str(e)}"}