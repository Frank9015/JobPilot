/**
 * JobPilot Dashboard — Frontend Application
 * Vanilla JS SPA — No framework needed.
 */

// ── API Wrapper ──────────────────────────────────────────────
async function api(endpoint, options = {}) {
    try {
        const res = await fetch(`/api/${endpoint}`, {
            headers: { 'Content-Type': 'application/json', ...options.headers },
            ...options,
        });
        return await res.json();
    } catch (err) {
        console.error(`API Error [${endpoint}]:`, err);
        return null;
    }
}

// ── Navigation ───────────────────────────────────────────────
document.querySelectorAll('.nav-tab').forEach(tab => {
    tab.addEventListener('click', () => {
        const page = tab.dataset.page;
        switchPage(page);
    });
});

function switchPage(pageName) {
    // Tabs
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
    document.querySelector(`.nav-tab[data-page="${pageName}"]`)?.classList.add('active');

    // Pages
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById(`page-${pageName}`)?.classList.add('active');

    // Load data
    if (pageName === 'dashboard') loadDashboard();
    if (pageName === 'jobs') loadJobs();
    if (pageName === 'profile') loadProfile();
    if (pageName === 'config') loadConfig();
}

// ── Toast Notifications ──────────────────────────────────────
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(40px)';
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

// ── Dashboard Page ───────────────────────────────────────────
async function loadDashboard() {
    loadStats();
    loadGeminiUsage();
    loadRecentJobs();
}

async function loadStats() {
    const stats = await api('jobs/stats');
    if (!stats) return;

    document.getElementById('kpi-total').textContent = stats.total;
    document.getElementById('kpi-scored').textContent = stats.scored;
    document.getElementById('kpi-cv-ready').textContent = stats.cv_ready;
    document.getElementById('kpi-applied').textContent = stats.applied;
    document.getElementById('kpi-avg-score').textContent =
        stats.avg_score > 0 ? `Promedio: ${stats.avg_score}%` : 'Sin evaluar';

    const portalText = Object.entries(stats.by_portal)
        .map(([k, v]) => `${capitalize(k)}: ${v}`)
        .join(' · ');
    document.getElementById('kpi-portals').textContent = portalText || 'Sin ofertas';
}

async function loadGeminiUsage() {
    const data = await api('gemini/usage');
    if (!data) return;

    const { today, limits } = data;

    document.getElementById('tokens-used').textContent = formatNumber(today.tokens_total);
    document.getElementById('tokens-limit').textContent =
        `de ${formatNumber(limits.token_limit)}`;
    document.getElementById('requests-used').textContent = today.requests;
    document.getElementById('requests-limit').textContent =
        `de ${limits.request_limit}`;
    document.getElementById('cache-hits').textContent = today.cache_hits;
    document.getElementById('cache-entries').textContent = today.cache_entries;

    // Progress bars
    setProgressBar('tokens-bar', limits.token_pct);
    setProgressBar('requests-bar', limits.request_pct);
}

function setProgressBar(id, pct) {
    const bar = document.getElementById(id);
    bar.style.width = `${Math.min(pct, 100)}%`;
    bar.classList.remove('warning', 'danger');
    if (pct >= 80) bar.classList.add('danger');
    else if (pct >= 50) bar.classList.add('warning');
}

async function loadRecentJobs() {
    const jobs = await api('jobs?limit=10');
    if (!jobs) return;

    const tbody = document.getElementById('recent-jobs-body');

    if (!jobs.length) {
        tbody.innerHTML = `<tr><td colspan="6" class="empty-state">
            <div class="icon">📭</div><p>No hay ofertas aún. Inicia una búsqueda.</p>
        </td></tr>`;
        return;
    }

    tbody.innerHTML = jobs.map(job => `
        <tr>
            <td style="max-width: 240px;">
                <a href="${job.url || '#'}" target="_blank" style="color: var(--text-accent); text-decoration: none;">
                    ${escapeHtml(job.title?.substring(0, 45) || '—')}
                </a>
            </td>
            <td>${escapeHtml(job.company?.substring(0, 20) || '—')}</td>
            <td><span style="text-transform: capitalize; font-size: 0.78rem; color: var(--text-secondary);">${job.portal}</span></td>
            <td>${renderScore(job.score)}</td>
            <td>${renderStatus(job.status)}</td>
            <td>
                ${['cv_ready', 'applied'].includes(job.status) 
                    ? `<a href="/api/jobs/${job.id}/cv/download.pdf" download="CV_Adaptado.pdf" target="_blank" class="btn btn-secondary" style="padding: 4px 8px; font-size: 0.7rem; text-decoration: none;">📄 PDF</a>`
                    : '<span style="color: var(--text-dim);">—</span>'
                }
            </td>
            <td style="font-size: 0.75rem; color: var(--text-dim);">${formatDate(job.scraped_at)}</td>
        </tr>
    `).join('');
}

// ── Jobs Page ────────────────────────────────────────────────
async function loadJobs() {
    const status = document.getElementById('filter-status')?.value || '';
    const portal = document.getElementById('filter-portal')?.value || '';

    let endpoint = 'jobs?limit=100';
    if (status) endpoint += `&status=${status}`;
    if (portal) endpoint += `&portal=${portal}`;

    const jobs = await api(endpoint);
    if (!jobs) return;

    const tbody = document.getElementById('all-jobs-body');

    if (!jobs.length) {
        tbody.innerHTML = `<tr><td colspan="9" class="empty-state">
            <div class="icon">🔍</div><p>No hay ofertas con esos filtros.</p>
        </td></tr>`;
        return;
    }

    tbody.innerHTML = jobs.map(job => `
        <tr>
            <td style="max-width: 220px;">
                <a href="${job.url || '#'}" target="_blank" style="color: var(--text-accent); text-decoration: none;">
                    ${escapeHtml(job.title?.substring(0, 40) || '—')}
                </a>
            </td>
            <td>${escapeHtml(job.company?.substring(0, 18) || '—')}</td>
            <td style="font-size: 0.78rem; color: var(--text-secondary);">${escapeHtml(job.location?.substring(0, 20) || '—')}</td>
            <td style="text-transform: capitalize; font-size: 0.78rem;">${job.portal}</td>
            <td>${renderScore(job.score)}</td>
            <td style="font-size: 0.78rem;">${job.score?.skill_match != null ? Math.round(job.score.skill_match) + '%' : '—'}</td>
            <td style="font-size: 0.78rem;">${job.score?.experience_match != null ? Math.round(job.score.experience_match) + '%' : '—'}</td>
            <td style="font-size: 0.72rem; color: var(--text-dim);">${job.score?.method || '—'}</td>
            <td>${renderStatus(job.status)}</td>
            <td>
                ${['cv_ready', 'applied'].includes(job.status) 
                    ? `<a href="/api/jobs/${job.id}/cv/download.pdf" download="CV_Adaptado.pdf" target="_blank" class="btn btn-secondary" style="padding: 4px 8px; font-size: 0.7rem; text-decoration: none;">📄 PDF</a>`
                    : '<span style="color: var(--text-dim);">—</span>'
                }
            </td>
        </tr>
    `).join('');
}

// ── Profile Page ─────────────────────────────────────────────
async function loadProfile() {
    const data = await api('profile');
    if (!data || !data.exists) {
        document.getElementById('profile-name').textContent = 'Sin perfil';
        document.getElementById('profile-email').textContent = 'Ejecuta el parseo de CV primero';
        return;
    }

    const initials = (data.full_name || '?').split(' ').map(w => w[0]).join('').substring(0, 2);
    document.getElementById('profile-avatar').textContent = initials;
    document.getElementById('profile-name').textContent = data.full_name || '—';
    document.getElementById('profile-email').textContent = data.email || '—';
    document.getElementById('profile-skills-count').textContent = data.total_skills;
    document.getElementById('profile-exp-count').textContent = data.total_experience;
    document.getElementById('profile-proj-count').textContent = data.total_projects;

    // Skills
    const container = document.getElementById('profile-skills');
    if (data.skills?.length) {
        container.innerHTML = data.skills.map(s => {
            const name = typeof s === 'string' ? s : s.name;
            return `<span class="skill-tag">${escapeHtml(name)}</span>`;
        }).join('');
    } else {
        container.innerHTML = '<span style="color: var(--text-dim)">Sin skills detectados</span>';
    }
}

// ── CV Upload ────────────────────────────────────────────────
const uploadArea = document.getElementById('upload-area');
if (uploadArea) {
    uploadArea.addEventListener('dragover', e => {
        e.preventDefault();
        uploadArea.classList.add('dragover');
    });
    uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('dragover');
    });
    uploadArea.addEventListener('drop', e => {
        e.preventDefault();
        uploadArea.classList.remove('dragover');
        if (e.dataTransfer.files.length) {
            uploadCVFile(e.dataTransfer.files[0]);
        }
    });
}

async function uploadCV(input) {
    if (input.files.length) uploadCVFile(input.files[0]);
}

async function uploadCVFile(file) {
    const resultEl = document.getElementById('upload-result');
    resultEl.innerHTML = '<span class="spinner"></span> Subiendo...';

    const formData = new FormData();
    formData.append('file', file);

    try {
        const res = await fetch('/api/profile/upload-cv', {
            method: 'POST',
            body: formData,
        });
        const data = await res.json();

        if (data.success) {
            resultEl.innerHTML = `<span style="color: var(--green);">✓ ${data.filename} (${data.size_kb} KB)</span>`;
            showToast(`CV subido: ${data.filename}`, 'success');
        } else {
            resultEl.innerHTML = `<span style="color: var(--red);">✗ Error al subir</span>`;
        }
    } catch (err) {
        resultEl.innerHTML = `<span style="color: var(--red);">✗ Error: ${err.message}</span>`;
    }
}

// ── Config Page ──────────────────────────────────────────────
async function loadConfig() {
    loadSessions();
    loadSystemInfo();
}

async function loadSessions() {
    const sessions = await api('sessions');
    if (!sessions) return;

    const grid = document.getElementById('semaphore-grid');

    if (!sessions.length) {
        grid.innerHTML = '<div class="empty-state"><p>Sin portales configurados</p></div>';
        return;
    }

    grid.innerHTML = sessions.map(s => `
        <div class="semaphore-item">
            <div class="semaphore-light ${s.status}"></div>
            <div class="semaphore-info">
                <div class="semaphore-portal">${s.portal}</div>
                <div class="semaphore-status">${s.status} ${s.reason ? '— ' + s.reason : ''}</div>
            </div>
            ${s.status !== 'active' ? `
            <button class="btn btn-secondary" onclick="triggerLogin('${s.portal}')" style="padding: 6px 12px; font-size: 0.75rem;">
                🔑 Login
            </button>
            ` : `
            <button class="btn btn-secondary" onclick="triggerLogin('${s.portal}')" style="padding: 6px 12px; font-size: 0.75rem; opacity: 0.7;">
                🔄 Re-Login
            </button>
            `}
        </div>
    `).join('');
}

async function triggerLogin(portal) {
    showToast(`Abriendo navegador para login en ${portal}...`, 'info');
    const data = await api(`sessions/${portal}/login`, { method: 'POST' });
    if (data?.success) {
        showToast(`Login en ${portal} exitoso.`, 'success');
    } else {
        showToast(data?.message || `Error en login de ${portal}`, 'error');
    }
    loadSessions();
}

async function loadSystemInfo() {
    const data = await api('control/status');
    if (!data) return;

    // Update header dots
    document.getElementById('db-dot').className =
        `status-dot ${data.db_connected ? 'green' : 'red'}`;
    document.getElementById('gemini-dot').className =
        `status-dot ${data.gemini_mode === 'mock' ? 'yellow' : 'green'}`;
    document.getElementById('gemini-mode').textContent =
        data.gemini_mode === 'mock' ? 'Gemini MOCK' : 'Gemini REAL';

    const tbody = document.getElementById('system-info');
    tbody.innerHTML = `
        <tr><td style="color: var(--text-dim);">Base de datos</td><td>${data.db_connected ? '🟢 Conectada' : '🔴 Desconectada'}</td></tr>
        <tr><td style="color: var(--text-dim);">Modo Gemini</td><td>${data.gemini_mode === 'mock' ? '🟡 Mock' : '🟢 Real'}</td></tr>
        <tr><td style="color: var(--text-dim);">Score mínimo</td><td>${data.min_score}%</td></tr>
        <tr><td style="color: var(--text-dim);">Browser</td><td>${data.headful ? 'Visible (headful)' : 'Headless'}</td></tr>
        <tr><td style="color: var(--text-dim);">Portales</td><td>${data.enabled_portals?.join(', ') || '—'}</td></tr>
        <tr><td style="color: var(--text-dim);">Tareas activas</td><td>${Object.keys(data.running_tasks || {}).join(', ') || 'Ninguna'}</td></tr>
    `;
}

// ── Control Actions ──────────────────────────────────────────
async function triggerAction(action) {
    const btnMap = {
        'scrape': 'btn-scrape',
        'score': 'btn-score',
        'generate-cvs': 'btn-generate',
    };
    const btn = document.getElementById(btnMap[action]);
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner"></span> Ejecutando...`;
    }

    const data = await api(`control/${action}`, { method: 'POST' });

    if (data?.success) {
        showToast(data.message, 'success');
    } else {
        showToast(data?.message || 'Error', 'error');
    }

    // Re-enable after 5s (task runs in background)
    setTimeout(() => {
        if (btn) {
            btn.disabled = false;
            const labels = {
                'scrape': 'Iniciar Búsqueda',
                'score': 'Evaluar Ofertas',
                'generate-cvs': 'Generar CVs',
            };
            btn.innerHTML = labels[action];
        }
        loadDashboard();
    }, 5000);
}

// ── Utilities ────────────────────────────────────────────────
function renderScore(scoreObj) {
    if (!scoreObj || scoreObj.total == null) return '<span style="color: var(--text-dim);">—</span>';
    const rounded = Math.round(scoreObj.total);
    let cls = 'low';
    if (rounded >= 70) cls = 'high';
    else if (rounded >= 50) cls = 'medium';
    
    let html = `<span class="score-badge ${cls}">${rounded}%</span>`;
    
    if (scoreObj.reasoning) {
        html = `
        <div class="score-wrapper">
            ${html}
            <span class="reasoning-icon">💡</span>
            <div class="reasoning-tooltip">
                <div class="reasoning-header">
                    <span style="font-size: 0.9rem;">🤖</span> Gemini Reasoning
                </div>
                ${escapeHtml(scoreObj.reasoning)}
            </div>
        </div>`;
    }
    return html;
}

function renderStatus(status) {
    return `<span class="status-tag ${status || 'new'}">${status || 'new'}</span>`;
}

function capitalize(str) {
    return str.charAt(0).toUpperCase() + str.slice(1);
}

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function formatNumber(n) {
    if (n == null) return '0';
    return n.toLocaleString('es-CL');
}

function formatDate(isoStr) {
    if (!isoStr) return '—';
    try {
        const d = new Date(isoStr);
        return d.toLocaleDateString('es-CL', { day: '2-digit', month: 'short' });
    } catch {
        return '—';
    }
}

// ── Auto-refresh ─────────────────────────────────────────────
setInterval(() => {
    const activePage = document.querySelector('.page.active')?.id;
    if (activePage === 'page-dashboard') loadDashboard();
}, 30000);

// ── Init ─────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    loadDashboard();
    loadSystemInfo();
});
