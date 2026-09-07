function openPdf(url, filename) {
  var overlay = document.getElementById('pdf-overlay');
  var frame = document.getElementById('pdf-frame');
  var title = document.getElementById('pdf-title');
  if (!overlay || !frame) return;
  title.textContent = filename || 'Contract PDF';
  frame.src = '/static/pdfjs/viewer.html?file=' + encodeURIComponent(url);
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
  if (form) form.addEventListener('submit', function () {
    var button = document.getElementById('assistant-send');
    if (button) { button.disabled = true; button.textContent = 'Working…'; }
  });
  var skillEditor = document.getElementById('skill-instructions');
  if (skillEditor && skillEditor.form) skillEditor.form.addEventListener('submit', function () {
    var prose = document.getElementById('skill-prose');
    if (prose && prose.style.display !== 'none') skillEditor.value = skillHtmlToMarkdown(prose);
  });
});
