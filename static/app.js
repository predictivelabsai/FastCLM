function openPdf(url, filename, quote) {
  var overlay = document.getElementById('pdf-overlay');
  var frame = document.getElementById('pdf-frame');
  var title = document.getElementById('pdf-title');
  if (!overlay || !frame) return;
  title.textContent = filename || 'Contract PDF';
  frame.src = '/static/pdfjs/viewer.html?file=' + encodeURIComponent(url) + (quote ? '#search=' + encodeURIComponent(quote) : '');
  overlay.classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closePdf() {
  var overlay = document.getElementById('pdf-overlay');
  var frame = document.getElementById('pdf-frame');
  if (overlay) overlay.classList.remove('open');
  if (frame) frame.src = 'about:blank';
  document.body.style.overflow = '';
}

function setSkillMode(mode) {
  var editor = document.getElementById('skill-instructions');
  if (!editor) return;
  var prose = document.getElementById('skill-prose');
  if (mode === 'prose' && !prose) {
    prose = document.createElement('div');
    prose.id = 'skill-prose';
    prose.className = 'skill-prose';
    prose.contentEditable = 'true';
    prose.setAttribute('role', 'textbox');
    prose.setAttribute('aria-label', 'Skill instructions prose editor');
    prose.innerHTML = skillMarkdownToHtml(editor.value);
    prose.addEventListener('input', function () { editor.value = skillHtmlToMarkdown(prose); });
    editor.parentNode.insertBefore(prose, editor);
  }
  if (prose) prose.style.display = mode === 'prose' ? 'block' : 'none';
  editor.style.display = mode === 'markdown' ? 'block' : 'none';
  document.querySelectorAll('.editor-mode').forEach(function (button) {
    button.classList.toggle('active', button.textContent.toLowerCase() === mode);
  });
}

function skillMarkdownToHtml(markdown) {
  var escape = function (value) { return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); };
  return markdown.split(/\n{2,}/).map(function (block) {
    var value = escape(block.trim());
    if (!value) return '';
    if (value.indexOf('### ') === 0) return '<h3>' + value.slice(4) + '</h3>';
    if (value.indexOf('## ') === 0) return '<h2>' + value.slice(3) + '</h2>';
    if (value.indexOf('# ') === 0) return '<h1>' + value.slice(2) + '</h1>';
    if (value.split('\n').every(function (line) { return line.indexOf('- ') === 0; })) {
      return '<ul>' + value.split('\n').map(function (line) { return '<li>' + line.slice(2) + '</li>'; }).join('') + '</ul>';
    }
    return '<p>' + value.replace(/\n/g, '<br>') + '</p>';
  }).join('');
}

function skillHtmlToMarkdown(host) {
  var blocks = [];
  host.childNodes.forEach(function (node) {
    var text = (node.innerText || node.textContent || '').trim();
    if (!text) return;
    if (node.nodeName === 'H1') blocks.push('# ' + text);
    else if (node.nodeName === 'H2') blocks.push('## ' + text);
    else if (node.nodeName === 'H3') blocks.push('### ' + text);
    else if (node.nodeName === 'UL' || node.nodeName === 'OL') {
      blocks.push(Array.from(node.querySelectorAll('li')).map(function (item) { return '- ' + item.innerText.trim(); }).join('\n'));
    } else blocks.push(text);
  });
  return blocks.join('\n\n') + '\n';
}

function streamElement(tag, className, text) {
  var node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function streamVisibleText(raw) {
  var visible = raw.replace(/\[\[cite:(\d+)\|[\s\S]*?\]\]/g, '[$1]');
  var unfinished = visible.lastIndexOf('[[cite:');
  if (unfinished >= 0 && visible.indexOf(']]', unfinished) < 0) visible = visible.slice(0, unfinished);
  return visible;
}

function appendStreamingMessage(messages, role, text) {
  var message = streamElement('div', 'assistant-message ' + role);
  var inner = streamElement('div', 'message-inner');
  inner.appendChild(streamElement('span', 'message-avatar', role === 'user' ? 'You' : 'AI'));
  var body = streamElement('div', 'stream-message-body');
  var receipts = streamElement('div', 'stream-receipts');
  var copy = streamElement('p', 'message-copy', text || '');
  body.appendChild(receipts);
  body.appendChild(copy);
  inner.appendChild(body);
  message.appendChild(inner);
  messages.appendChild(message);
  messages.scrollTop = messages.scrollHeight;
  return {message: message, receipts: receipts, copy: copy};
}

function updateStreamingActivity(receipts, event) {
  var id = 'stream-tool-' + String(event.tool || 'tool').replace(/[^a-z0-9_-]/gi, '-');
  var row = receipts.querySelector('#' + id);
  if (!row) {
    row = streamElement('div', 'stream-receipt running');
    row.id = id;
    row.appendChild(streamElement('span', 'stream-tool-icon', '↻'));
    row.appendChild(streamElement('span', 'stream-tool-label', event.label || event.tool));
    receipts.appendChild(row);
  }
  row.classList.toggle('running', event.status === 'running');
  row.classList.toggle('complete', event.status === 'complete');
  row.querySelector('.stream-tool-icon').textContent = event.status === 'complete' ? '✓' : '↻';
  row.querySelector('.stream-tool-label').textContent = event.label || event.tool;
  row.title = event.detail || '';
}

async function submitAssistantStream(form) {
  var messages = document.getElementById('assistant-messages');
  var question = document.getElementById('assistant-question');
  var button = document.getElementById('assistant-send');
  if (!messages || !question || !question.value.trim()) return;
  var text = question.value.trim();
  var payload = new FormData(form);
  appendStreamingMessage(messages, 'user', text);
  var live = appendStreamingMessage(messages, 'assistant', '');
  var raw = '';
  button.disabled = true;
  button.textContent = 'Working…';
  question.value = '';
  try {
    var response = await fetch(form.dataset.streamUrl, {method: 'POST', body: payload, headers: {'Accept': 'application/x-ndjson'}});
    if (!response.ok || !response.body) throw new Error('Assistant stream could not be opened.');
    var reader = response.body.getReader();
    var decoder = new TextDecoder();
    var buffer = '';
    while (true) {
      var part = await reader.read();
      buffer += decoder.decode(part.value || new Uint8Array(), {stream: !part.done});
      var lines = buffer.split('\n');
      buffer = lines.pop() || '';
      lines.forEach(function (line) {
        if (!line.trim()) return;
        var event = JSON.parse(line);
        if (event.type === 'activity') updateStreamingActivity(live.receipts, event);
        if (event.type === 'token') {
          raw += event.text || '';
          live.copy.textContent = streamVisibleText(raw);
        }
        if (event.type === 'complete') live.copy.textContent = event.answer || streamVisibleText(raw);
        if (event.type === 'error') throw new Error(event.message || 'Assistant request failed.');
      });
      messages.scrollTop = messages.scrollHeight;
      if (part.done) break;
    }
    window.setTimeout(function () { window.location.reload(); }, 500);
  } catch (error) {
    live.copy.textContent = error.message || 'Assistant request failed.';
    live.message.classList.add('stream-error');
    button.disabled = false;
    button.textContent = 'Ask FastCLM';
    question.value = text;
  }
}

document.addEventListener('keydown', function (event) {
  if (event.key === 'Escape') closePdf();
  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
    var form = document.getElementById('assistant-form');
    if (form) form.requestSubmit();
  }
});

document.addEventListener('DOMContentLoaded', function () {
  var messages = document.getElementById('assistant-messages');
  if (messages) messages.scrollTop = messages.scrollHeight;
  if (document.getElementById('skill-instructions')) setSkillMode('prose');
  var form = document.getElementById('assistant-form');
  if (form && form.dataset.streamUrl && window.ReadableStream) form.addEventListener('submit', function (event) {
    event.preventDefault();
    submitAssistantStream(form);
  });
  var skillEditor = document.getElementById('skill-instructions');
  if (skillEditor && skillEditor.form) skillEditor.form.addEventListener('submit', function () {
    var prose = document.getElementById('skill-prose');
    if (prose && prose.style.display !== 'none') skillEditor.value = skillHtmlToMarkdown(prose);
  });
});
