#!/usr/bin/env python3
"""Simple web interface to browse Chroma chunks."""

from flask import Flask, render_template_string, request, jsonify
from core.vectorstore import get_chroma_collection
import json

app = Flask(__name__)
collection = get_chroma_collection()

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Chroma Chunks Viewer</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f5f5; }
        .header { background: #2c3e50; color: white; padding: 20px; text-align: center; }
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }

        .controls {
            background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            display: flex; gap: 10px; flex-wrap: wrap;
            align-items: center;
        }

        input, select, button { padding: 10px 15px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px; }
        button { background: #3498db; color: white; cursor: pointer; border: none; }
        button:hover { background: #2980b9; }

        .stats { font-size: 14px; color: #666; }
        .stats strong { color: #2c3e50; }

        .chunks-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(500px, 1fr)); gap: 15px; }

        .chunk {
            background: white; border-radius: 8px; padding: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            border-left: 4px solid #3498db;
            overflow: hidden;
        }

        .chunk-meta {
            display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 15px;
            font-size: 12px;
        }

        .tag {
            background: #ecf0f1; padding: 4px 8px; border-radius: 3px;
            font-weight: 500; color: #2c3e50;
        }

        .tag.source { background: #3498db; color: white; }
        .tag.topic { background: #27ae60; color: white; }
        .tag.form { background: #e67e22; color: white; }

        .chunk-text {
            color: #333; line-height: 1.6; font-size: 14px;
            max-height: 300px; overflow-y: auto;
            padding: 15px; background: #f9f9f9; border-radius: 4px;
            border: 1px solid #eee;
        }

        .highlight { background: #fff3cd; padding: 2px 4px; border-radius: 2px; }

        .pagination {
            display: flex; gap: 10px; margin-top: 30px; justify-content: center;
            align-items: center;
        }

        .pagination button:disabled { background: #bdc3c7; cursor: not-allowed; }

        .empty {
            text-align: center; padding: 60px 20px; color: #95a5a6;
        }

        h1 { font-size: 24px; margin: 0; }
        h2 { font-size: 16px; margin: 10px 0; color: #2c3e50; }
        .loading { text-align: center; padding: 40px; color: #95a5a6; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🔍 Chroma Chunks Viewer</h1>
    </div>

    <div class="container">
        <div class="controls">
            <input type="text" id="search" placeholder="Search by text..." style="flex: 1; min-width: 200px;">
            <select id="sourceFilter">
                <option value="">All sources</option>
            </select>
            <select id="topicFilter">
                <option value="">All topics</option>
            </select>
            <button onclick="search()">Search</button>
            <button onclick="loadAll()">Reset</button>
            <div class="stats" id="stats"></div>
        </div>

        <div id="chunks" class="chunks-grid"></div>

        <div class="pagination">
            <button onclick="previousPage()" id="prevBtn">← Previous</button>
            <span id="pageInfo"></span>
            <button onclick="nextPage()" id="nextBtn">Next →</button>
        </div>
    </div>

    <script>
        let allChunks = [];
        let filteredChunks = [];
        let currentPage = 1;
        const pageSize = 12;
        let sources = new Set();
        let topics = new Set();

        async function loadAll() {
            document.getElementById('chunks').innerHTML = '<div class="loading">Loading...</div>';
            try {
                const response = await fetch('/api/chunks?limit=1000');
                const data = await response.json();
                allChunks = data.chunks;
                filteredChunks = [...allChunks];

                // Collect unique sources and topics
                allChunks.forEach(chunk => {
                    if (chunk.source_id) sources.add(chunk.source_id);
                    if (chunk.topic) topics.add(chunk.topic);
                });

                // Populate filters
                const sourceSelect = document.getElementById('sourceFilter');
                const topicSelect = document.getElementById('topicFilter');

                [...sources].sort().forEach(s => {
                    const opt = document.createElement('option');
                    opt.value = s;
                    opt.textContent = s;
                    sourceSelect.appendChild(opt);
                });

                [...topics].sort().forEach(t => {
                    const opt = document.createElement('option');
                    opt.value = t;
                    opt.textContent = t;
                    topicSelect.appendChild(opt);
                });

                currentPage = 1;
                renderPage();
            } catch (error) {
                console.error('Error:', error);
                document.getElementById('chunks').innerHTML = '<div class="empty">Error loading chunks</div>';
            }
        }

        function renderPage() {
            const start = (currentPage - 1) * pageSize;
            const end = start + pageSize;
            const pageChunks = filteredChunks.slice(start, end);

            const html = pageChunks.map(chunk => `
                <div class="chunk">
                    <div class="chunk-meta">
                        <span class="tag source">${chunk.source_id || 'unknown'}</span>
                        ${chunk.topic ? `<span class="tag topic">${chunk.topic}</span>` : ''}
                        ${chunk.form_id ? `<span class="tag form">${chunk.form_id}</span>` : ''}
                    </div>
                    <div class="chunk-text">${chunk.text}</div>
                </div>
            `).join('');

            document.getElementById('chunks').innerHTML = html || '<div class="empty">No chunks found</div>';

            const totalPages = Math.ceil(filteredChunks.length / pageSize);
            document.getElementById('pageInfo').textContent = `Page ${currentPage} of ${totalPages}`;
            document.getElementById('prevBtn').disabled = currentPage === 1;
            document.getElementById('nextBtn').disabled = currentPage === totalPages;
            document.getElementById('stats').textContent = `Showing ${filteredChunks.length} chunks`;
        }

        function nextPage() {
            const totalPages = Math.ceil(filteredChunks.length / pageSize);
            if (currentPage < totalPages) {
                currentPage++;
                renderPage();
            }
        }

        function previousPage() {
            if (currentPage > 1) {
                currentPage--;
                renderPage();
            }
        }

        async function search() {
            const query = document.getElementById('search').value;
            const source = document.getElementById('sourceFilter').value;
            const topic = document.getElementById('topicFilter').value;

            let filtered = allChunks;

            if (query) {
                filtered = filtered.filter(c =>
                    c.text.toLowerCase().includes(query.toLowerCase())
                );
            }

            if (source) {
                filtered = filtered.filter(c => c.source_id === source);
            }

            if (topic) {
                filtered = filtered.filter(c => c.topic === topic);
            }

            filteredChunks = filtered;
            currentPage = 1;
            renderPage();
        }

        // Load on page start
        loadAll();
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/chunks')
def get_chunks():
    limit = request.args.get('limit', default=100, type=int)
    results = collection.get(limit=limit, include=['documents', 'metadatas'])

    chunks = []
    for i, doc in enumerate(results['documents']):
        meta = results['metadatas'][i]
        chunks.append({
            'text': doc,
            'source_id': meta.get('source_id'),
            'topic': meta.get('topic'),
            'form_id': meta.get('form_id'),
            'section': meta.get('section'),
        })

    return jsonify({'chunks': chunks, 'total': collection.count()})

if __name__ == '__main__':
    print("Serving on http://localhost:5000")
    print("Ctrl+C to stop")
    app.run(debug=False, port=5000)
