// === CarbCount PWA — App Logic ===

// --- API Helper ---
async function apiRequest(path, options = {}) {
    const token = sessionStorage.getItem('app_token');
    if (!token && path !== '/health') {
        showView('token');
        throw new Error('No token');
    }

    const response = await fetch(`/api${path}`, {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
            ...options.headers,
        },
    });

    if (response.status === 401) {
        sessionStorage.removeItem('app_token');
        showView('token');
        throw new Error('Unauthorized');
    }

    if (response.status === 429) {
        const data = await response.json();
        showError(`Rate limited: ${data.detail}`);
        throw new Error('Rate limited');
    }

    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || `API error: ${response.status}`);
    }

    return response.json();
}

// --- View Management ---
function showView(name) {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));

    const view = document.getElementById(`${name}-view`);
    if (view) view.classList.add('active');

    const tab = document.querySelector(`.nav-tab[data-view="${name}"]`);
    if (tab) tab.classList.add('active');

    const nav = document.getElementById('nav-tabs');
    if (name === 'token') {
        nav.style.display = 'none';
    } else {
        nav.style.display = 'flex';
    }

    // Load data for views
    if (name === 'history') loadHistory();
    if (name === 'accuracy') loadAccuracy();
}

function showError(msg) {
    const banner = document.getElementById('error-banner');
    banner.textContent = msg;
    banner.classList.add('active');
    setTimeout(() => banner.classList.remove('active'), 8000);
}

function hideError() {
    document.getElementById('error-banner').classList.remove('active');
}

// --- Token Entry ---
function initToken() {
    const tokenInput = document.getElementById('token-input');
    const tokenSubmit = document.getElementById('token-submit');

    async function submitToken() {
        const token = tokenInput.value.trim();
        if (!token) return;

        sessionStorage.setItem('app_token', token);

        try {
            // Validate token with a test request
            await apiRequest('/history?limit=1');
            showView('estimate');
        } catch (e) {
            sessionStorage.removeItem('app_token');
            showError('Invalid token. Please try again.');
            showView('token');
        }
    }

    tokenSubmit.addEventListener('click', submitToken);
    tokenInput.addEventListener('keydown', e => {
        if (e.key === 'Enter') submitToken();
    });
}

// --- Estimate ---
let loadingInterval = null;

function initEstimate() {
    const queryInput = document.getElementById('query-input');
    const notesToggle = document.getElementById('notes-toggle');
    const notesSection = document.getElementById('notes-section');
    const notesArrow = document.getElementById('notes-arrow');
    const estimateBtn = document.getElementById('estimate-btn');

    notesToggle.addEventListener('click', () => {
        notesSection.classList.toggle('open');
        notesArrow.textContent = notesSection.classList.contains('open') ? '\u25BC' : '\u25B6';
    });

    estimateBtn.addEventListener('click', () => submitEstimate());
    queryInput.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            queryInput.blur();
            submitEstimate();
        }
    });
}

async function submitEstimate() {
    const query = document.getElementById('query-input').value.trim();
    if (!query) return;

    const notes = document.getElementById('notes-input')?.value.trim() || null;

    // Show loading
    document.getElementById('estimate-form').style.display = 'none';
    document.getElementById('results').classList.remove('active');
    document.getElementById('loading').classList.add('active');
    hideError();

    let elapsed = 0;
    const timerEl = document.getElementById('loading-timer');
    loadingInterval = setInterval(() => {
        elapsed += 0.1;
        timerEl.textContent = `${elapsed.toFixed(1)}s`;
    }, 100);

    try {
        const body = { query };
        if (notes) body.user_notes = notes;

        const data = await apiRequest('/estimate', {
            method: 'POST',
            body: JSON.stringify(body),
        });

        renderResults(data);
    } catch (e) {
        showError(e.message);
        document.getElementById('estimate-form').style.display = 'flex';
    } finally {
        clearInterval(loadingInterval);
        document.getElementById('loading').classList.remove('active');
    }
}

function renderResults(data) {
    const container = document.getElementById('results');
    const macros = data.macros;
    const warsaw = data.warsaw;
    const totals = macros.meal_totals;

    let html = '';

    // Meal total card
    html += `
    <div class="result-card">
        <div class="card-header">
            <span class="card-title">Meal Total</span>
            ${data.cached ? '<span class="cached-badge">CACHED</span>' : ''}
        </div>
        <div class="macro-grid">
            <div class="macro-item">
                <span class="macro-label">Net Carbs</span>
                <span class="macro-value highlight">${totals.net_carbs_g}<span class="macro-unit">g</span></span>
            </div>
            <div class="macro-item">
                <span class="macro-label">Protein</span>
                <span class="macro-value">${totals.protein_g}<span class="macro-unit">g</span></span>
            </div>
            <div class="macro-item">
                <span class="macro-label">Fat</span>
                <span class="macro-value">${totals.fat_g}<span class="macro-unit">g</span></span>
            </div>
            <div class="macro-item">
                <span class="macro-label">Calories</span>
                <span class="macro-value">${totals.calories}<span class="macro-unit">kcal</span></span>
            </div>
        </div>
    </div>`;

    // Warsaw / absorption card
    const profileClass = `profile-${warsaw.profile}`;
    html += `
    <div class="result-card">
        <div class="card-header">
            <span class="card-title">Absorption (Warsaw Method)</span>
            <span class="profile-badge ${profileClass}">${warsaw.profile}</span>
        </div>
        <div class="warsaw-grid">
            <div class="warsaw-item">
                <span class="warsaw-label">FPU</span>
                <span class="warsaw-value">${warsaw.fpu}</span>
            </div>
            <div class="warsaw-item">
                <span class="warsaw-label">Duration</span>
                <span class="warsaw-value">${warsaw.absorption_duration_hours}h</span>
            </div>
            <div class="warsaw-item">
                <span class="warsaw-label">Peak</span>
                <span class="warsaw-value">~${warsaw.peak_glucose_impact_minutes}min</span>
            </div>
            <div class="warsaw-item">
                <span class="warsaw-label">F+P Carb Equiv</span>
                <span class="warsaw-value">${warsaw.fpu_carb_equivalent_g}g</span>
            </div>
        </div>
        <div style="margin-bottom: 12px;">
            <span class="warsaw-label">Total Carb Impact</span>
            <span class="warsaw-value highlight" style="font-size: 22px; display: block; margin-top: 4px;">${warsaw.total_carb_impact_g}<span class="macro-unit">g</span></span>
        </div>
        ${warsaw.notes ? `<div class="warsaw-notes">${escapeHtml(warsaw.notes)}</div>` : ''}
    </div>`;

    // Item breakdown card
    if (macros.items && macros.items.length > 0) {
        html += `<div class="result-card">
            <div class="card-header">
                <span class="card-title">Item Breakdown</span>
            </div>`;

        macros.items.forEach((item, i) => {
            const confClass = `confidence-${item.confidence}`;
            const confIcon = item.confidence === 'high' ? '\u2713' : item.confidence === 'medium' ? '~' : '!';

            html += `
            <div class="item-row" onclick="toggleItemDetail(${i})">
                <div class="item-summary">
                    <div style="flex: 1; min-width: 0;">
                        <div class="item-name">${escapeHtml(item.name)}</div>
                        <div class="item-portion">${escapeHtml(item.portion)}</div>
                    </div>
                    <span class="item-carbs">${item.net_carbs_g}g C</span>
                </div>
                <div class="item-meta">
                    <span>P: ${item.protein_g}g</span>
                    <span>F: ${item.fat_g}g</span>
                    <span class="confidence-badge ${confClass}">${item.confidence} ${confIcon}</span>
                </div>
                <div class="item-detail" id="item-detail-${i}">
                    <div class="detail-row"><span>Calories</span><span>${item.calories} kcal</span></div>
                    <div class="detail-row"><span>Total Carbs</span><span>${item.total_carbs_g}g</span></div>
                    <div class="detail-row"><span>Fiber</span><span>${item.fiber_g}g</span></div>
                    <div class="detail-row"><span>Net Carbs</span><span>${item.net_carbs_g}g</span></div>
                    <div class="detail-row"><span>Protein</span><span>${item.protein_g}g</span></div>
                    <div class="detail-row"><span>Fat</span><span>${item.fat_g}g</span></div>
                    <div class="detail-row"><span>Source</span><span>${escapeHtml(item.source)}</span></div>
                    ${item.confidence_note ? `<div class="detail-row"><span>Note</span><span>${escapeHtml(item.confidence_note)}</span></div>` : ''}
                    ${renderSourceValues(item.source_values_seen)}
                </div>
            </div>`;
        });

        html += `</div>`;
    }

    // Assumptions
    if (macros.meta && macros.meta.assumptions && macros.meta.assumptions.length > 0) {
        html += `
        <div class="result-card meta-section">
            <div class="card-header">
                <span class="card-title" style="color: var(--warning);">Assumptions Made</span>
            </div>
            <ul class="assumption-list">
                ${macros.meta.assumptions.map(a => `<li>${escapeHtml(a)}</li>`).join('')}
            </ul>
        </div>`;
    }

    // Action buttons
    html += `
    <div class="action-row">
        <button class="btn btn-secondary" style="flex: 1;" onclick="openCorrection('${data.id}', ${totals.net_carbs_g}, ${totals.protein_g}, ${totals.fat_g})">Correct This Estimate</button>
        <button class="btn btn-primary" style="flex: 1;" onclick="newQuery()">New Query</button>
    </div>`;

    // Processing time
    html += `<div style="text-align: center; font-size: 11px; color: var(--text-dim); margin-top: 8px; font-family: var(--font-mono);">
        ${(data.processing_time_ms / 1000).toFixed(1)}s${data.cached ? ' (cached)' : ''} | ${macros.meta?.sources_consulted?.length || 0} sources
    </div>`;

    container.innerHTML = html;
    container.classList.add('active');
}

function renderSourceValues(sv) {
    if (!sv) return '';
    let html = '<div class="source-values"><div class="source-values-title">Source Values Seen</div><div class="source-values-list">';
    if (sv.net_carbs_g?.length) html += `Carbs: [${sv.net_carbs_g.join(', ')}]g<br>`;
    if (sv.protein_g?.length) html += `Protein: [${sv.protein_g.join(', ')}]g<br>`;
    if (sv.fat_g?.length) html += `Fat: [${sv.fat_g.join(', ')}]g`;
    html += '</div></div>';
    return html;
}

function toggleItemDetail(index) {
    const detail = document.getElementById(`item-detail-${index}`);
    if (detail) detail.classList.toggle('open');
}

function newQuery() {
    document.getElementById('results').classList.remove('active');
    document.getElementById('results').innerHTML = '';
    document.getElementById('estimate-form').style.display = 'flex';
    document.getElementById('query-input').value = '';
    document.getElementById('notes-input').value = '';
    document.getElementById('query-input').focus();
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// --- Correction Modal ---
function openCorrection(id, carbs, protein, fat) {
    document.getElementById('correction-id').value = id;
    document.getElementById('correction-carbs').value = '';
    document.getElementById('correction-carbs').placeholder = `Estimated: ${carbs}g`;
    document.getElementById('correction-protein').value = '';
    document.getElementById('correction-protein').placeholder = `Estimated: ${protein}g`;
    document.getElementById('correction-fat').value = '';
    document.getElementById('correction-fat').placeholder = `Estimated: ${fat}g`;
    document.getElementById('correction-notes').value = '';
    document.getElementById('correction-modal').classList.add('active');
}

function closeCorrection() {
    document.getElementById('correction-modal').classList.remove('active');
}

async function submitCorrection() {
    const id = document.getElementById('correction-id').value;
    const carbs = document.getElementById('correction-carbs').value;
    const protein = document.getElementById('correction-protein').value;
    const fat = document.getElementById('correction-fat').value;
    const notes = document.getElementById('correction-notes').value.trim();

    const body = {};
    if (carbs !== '') body.actual_net_carbs_g = parseFloat(carbs);
    if (protein !== '') body.actual_protein_g = parseFloat(protein);
    if (fat !== '') body.actual_fat_g = parseFloat(fat);
    if (notes) body.notes = notes;

    if (Object.keys(body).length === 0 || (Object.keys(body).length === 1 && body.notes)) {
        showError('Please enter at least one corrected value.');
        return;
    }

    try {
        await apiRequest(`/history/${id}/correct`, {
            method: 'PATCH',
            body: JSON.stringify(body),
        });
        closeCorrection();
        showError(''); // Clear any error
        // Show a brief success indicator
        const banner = document.getElementById('error-banner');
        banner.textContent = 'Correction saved successfully.';
        banner.style.background = 'rgba(52, 211, 153, 0.1)';
        banner.style.borderColor = 'rgba(52, 211, 153, 0.3)';
        banner.style.color = '#34d399';
        banner.classList.add('active');
        setTimeout(() => {
            banner.classList.remove('active');
            banner.style.background = '';
            banner.style.borderColor = '';
            banner.style.color = '';
        }, 3000);
    } catch (e) {
        showError(`Correction failed: ${e.message}`);
    }
}

function initCorrection() {
    document.getElementById('correction-cancel').addEventListener('click', closeCorrection);
    document.getElementById('correction-submit').addEventListener('click', submitCorrection);
    document.getElementById('correction-modal').addEventListener('click', e => {
        if (e.target === document.getElementById('correction-modal')) closeCorrection();
    });
}

// --- History ---
let historyOffset = 0;
const HISTORY_PAGE_SIZE = 20;

async function loadHistory(reset = true) {
    if (reset) historyOffset = 0;

    const search = document.getElementById('history-search')?.value.trim() || '';
    const params = new URLSearchParams({ limit: HISTORY_PAGE_SIZE, offset: historyOffset });
    if (search) params.set('search', search);

    try {
        const data = await apiRequest(`/history?${params}`);
        const list = document.getElementById('history-list');

        if (reset) list.innerHTML = '';

        if (data.items.length === 0 && reset) {
            list.innerHTML = '<div class="history-empty">No estimates yet. Try making your first query!</div>';
            document.getElementById('load-more').style.display = 'none';
            return;
        }

        data.items.forEach(item => {
            const div = document.createElement('div');
            div.className = 'history-item';
            div.onclick = () => openHistoryItem(item.id);
            div.innerHTML = `
                <div class="history-query">${escapeHtml(item.query)}</div>
                <div class="history-macros">
                    <span>C: ${item.net_carbs_g}g</span>
                    <span>P: ${item.protein_g}g</span>
                    <span>F: ${item.fat_g}g</span>
                    ${item.fpu != null ? `<span>FPU: ${item.fpu}</span>` : ''}
                    ${item.profile ? `<span class="profile-badge profile-${item.profile}" style="font-size:9px;padding:1px 5px;">${item.profile}</span>` : ''}
                    ${item.has_correction ? '<span style="color: var(--success);">corrected</span>' : ''}
                </div>
                <div class="history-time">${formatTime(item.timestamp)} ${item.calories ? `| ${item.calories} kcal` : ''}</div>
            `;
            list.appendChild(div);
        });

        historyOffset += data.items.length;
        document.getElementById('load-more').style.display =
            historyOffset < data.total ? 'block' : 'none';
    } catch (e) {
        if (e.message !== 'No token' && e.message !== 'Unauthorized') {
            showError(`Failed to load history: ${e.message}`);
        }
    }
}

async function openHistoryItem(id) {
    try {
        const data = await apiRequest(`/history/${id}`);
        // Switch to estimate view and show results
        showView('estimate');
        document.getElementById('estimate-form').style.display = 'none';
        document.getElementById('loading').classList.remove('active');
        renderResults(data);
    } catch (e) {
        showError(`Failed to load estimate: ${e.message}`);
    }
}

function formatTime(isoString) {
    const d = new Date(isoString);
    const now = new Date();
    const diffMs = now - d;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return d.toLocaleDateString();
}

function initHistory() {
    let searchTimeout;
    document.getElementById('history-search').addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => loadHistory(true), 400);
    });
    document.getElementById('history-refresh').addEventListener('click', () => loadHistory(true));
    document.getElementById('load-more').addEventListener('click', () => loadHistory(false));
}

// --- Accuracy ---
async function loadAccuracy() {
    try {
        const data = await apiRequest('/accuracy');
        const container = document.getElementById('accuracy-content');

        if (data.total_estimates === 0) {
            container.innerHTML = '<div class="history-empty">No estimates yet.</div>';
            return;
        }

        let html = `
        <div class="accuracy-card">
            <div class="card-header">
                <span class="card-title">Overview</span>
            </div>
            <div class="stat-grid">
                <div class="stat-item">
                    <div class="stat-value">${data.total_estimates}</div>
                    <div class="stat-label">Total Estimates</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">${data.total_corrected}</div>
                    <div class="stat-label">Corrected</div>
                </div>
            </div>
        </div>`;

        if (data.carb_accuracy) {
            const acc = data.carb_accuracy;
            html += `
            <div class="accuracy-card">
                <div class="card-header">
                    <span class="card-title">Carb Estimation Accuracy</span>
                </div>
                <div class="stat-grid">
                    <div class="stat-item">
                        <div class="stat-value">${acc.mean_absolute_error_g}g</div>
                        <div class="stat-label">Mean Error</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-value">${acc.median_absolute_error_g}g</div>
                        <div class="stat-label">Median Error</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-value">${acc.within_5g_pct}%</div>
                        <div class="stat-label">Within 5g</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-value">${acc.within_10g_pct}%</div>
                        <div class="stat-label">Within 10g</div>
                    </div>
                </div>
                <div style="text-align: center; margin-top: 16px; font-size: 13px; color: var(--text-secondary);">
                    Bias: ${escapeHtml(acc.bias)}
                </div>
            </div>`;
        } else {
            html += `<div class="accuracy-card">
                <div style="text-align: center; padding: 20px; color: var(--text-dim);">
                    No corrections submitted yet. Use "Correct This Estimate" after checking actual nutrition values.
                </div>
            </div>`;
        }

        container.innerHTML = html;
    } catch (e) {
        if (e.message !== 'No token' && e.message !== 'Unauthorized') {
            showError(`Failed to load accuracy: ${e.message}`);
        }
    }
}

// --- Navigation ---
function initNav() {
    document.querySelectorAll('.nav-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            showView(tab.dataset.view);
        });
    });
}

// --- Init ---
function init() {
    initToken();
    initEstimate();
    initCorrection();
    initHistory();
    initNav();

    // Check for existing token
    if (sessionStorage.getItem('app_token')) {
        showView('estimate');
    } else {
        showView('token');
    }

    // Register service worker
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('sw.js').catch(() => {});
    }
}

document.addEventListener('DOMContentLoaded', init);
