function togglePlanProgressCollapse() {
            const content = document.getElementById('planProgressContent');
            const btn = document.getElementById('planProgressCollapseBtn');

            if (content.classList.contains('expanded')) {
                content.classList.remove('expanded');
                content.style.maxHeight = '0px';
                btn.classList.add('collapsed');
            } else {
                content.classList.add('expanded');
                content.style.maxHeight = content.scrollHeight + 'px';
                btn.classList.remove('collapsed');
            }
        }

        function updateTopPlanProgress(progress) {
            const container = document.getElementById('planProgressContainer');
            const statsElement = document.getElementById('topPlanProgressStats');
            const listElement = document.getElementById('topPlanProgressList');
            if (!progress || !progress.plan_enabled || !progress.plan_should_display) {
                clearTaskPlanProgress();
                return;
            }
            const steps = (progress && progress.steps) || [];

            const total = steps.length;
            const completed = steps.filter(step => step.status === 'completed').length;
            const inProgress = steps.filter(step => step.status === 'in_progress').length;
            const failed = steps.filter(step => step.status === 'failed').length;

            const statItems = [
                `Total: ${total}`,
                `Completed: ${completed}`,
                `In Progress: ${inProgress}`
            ];
            if (failed > 0) statItems.push(`Failed: ${failed}`);

            statsElement.innerHTML = statItems.map(item => `<span class="progress-stat">${escapeHtml(item)}</span>`).join('');

            listElement.innerHTML = '';
            steps.forEach(step => {
                const item = document.createElement('li');
                item.className = `plan-progress-item ${step.status || 'pending'}`;

                const metaPills = [];
                if (step.status) metaPills.push(step.status);

                const notes = [];
                if (step.notes) notes.push(step.notes);
                if (step.acceptance) notes.push(step.acceptance);

                item.innerHTML = `
                    <div class="plan-step-marker"></div>
                    <div class="plan-step-body">
                        <div class="plan-step-topline">
                            <div class="plan-step-title">${escapeHtml(step.title || step.kind || 'Untitled step')}</div>
                            <div class="plan-step-meta">
                                ${metaPills.map(item => `<span class="plan-step-pill">${escapeHtml(item)}</span>`).join('')}
                            </div>
                        </div>
                        ${notes.length ? `<div class="plan-step-notes">${escapeHtml(notes.join(' | '))}</div>` : ''}
                    </div>
                `;
                listElement.appendChild(item);
            });

            container.style.display = 'flex';

            // Maintain collapsed state; only update height if already expanded
            const content = document.getElementById('planProgressContent');
            if (content.classList.contains('expanded')) {
                content.style.maxHeight = content.scrollHeight + 'px';
            } else {
                content.style.maxHeight = '0px';
            }
        }

        function clearTaskPlanProgress() {
            const container = document.getElementById('planProgressContainer');
            const content = document.getElementById('planProgressContent');
            const listElement = document.getElementById('topPlanProgressList');
            const statsElement = document.getElementById('topPlanProgressStats');
            const btn = document.getElementById('planProgressCollapseBtn');

            listElement.innerHTML = '';
            statsElement.innerHTML = `
                <span class="progress-stat">Total: 0</span>
                <span class="progress-stat">Completed: 0</span>
                <span class="progress-stat">In Progress: 0</span>
            `;
            content.classList.remove('expanded');
            content.style.maxHeight = '0px';
            btn.classList.add('collapsed');
            container.style.display = 'none';
        }


