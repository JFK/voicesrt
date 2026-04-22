/** Data loading, saving, and glossary management — uses Alpine `this`. */

import { validateTimes } from './time-utils.js';

// Monotonic uid for x-for keying — keeps DOM state anchored to the original
// segment across add/delete/merge shifts.
var _uidSeq = 0;
export function nextSegmentUid() { return ++_uidSeq; }

export function createSaveManager(jobId, i18n) {
    return {
        debounceSave() {
            if (this._saveTimer) clearTimeout(this._saveTimer);
            var self = this;
            this._saveTimer = setTimeout(function () { self.saveSegments(); }, 1000);
        },

        async saveSegments() {
            // Re-entrancy guard: mark dirty instead of dropping the call so
            // edits made during a slow save still reach the server.
            if (this.saving) {
                this._saveDirty = true;
                return;
            }
            var errors = validateTimes(this.segments);
            if (errors.length > 0) {
                this.saveMsg = i18n.timeError + ': ' + errors[0];
                this.saveError = true;
                return;
            }
            this.saving = true;
            this._saveDirty = false;
            this.saveMsg = '';
            try {
                var res = await fetch('/api/jobs/' + jobId + '/segments', {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({segments: this.segments}),
                });
                if (!res.ok) {
                    var err = await res.json().catch(function () { return null; });
                    var msg = (err && err.error && err.error.message) || 'Save failed';
                    throw new Error(msg);
                }
                var now = new Date();
                var time = now.toLocaleTimeString('ja-JP', {hour: '2-digit', minute: '2-digit', second: '2-digit'});
                this.saveMsg = time + ' ' + i18n.saved;
                this.saveError = false;
            } catch (e) {
                this.saveMsg = e.message;
                this.saveError = true;
                showToast(e.message);
            } finally {
                this.saving = false;
                if (this._saveDirty) {
                    this._saveDirty = false;
                    this.debounceSave();
                }
            }
        },

        async loadSegments() {
            try {
                var res = await fetch('/api/jobs/' + jobId + '/segments');
                if (!res.ok) throw new Error('Failed to load segments');
                var data = await res.json();
                var segs = data.segments || [];
                segs.forEach(function (s) { s._uid = nextSegmentUid(); });
                this.segments = segs;
                this.verifiedIndices = data.verified_indices || [];
                this._verifiedSet = new Set(this.verifiedIndices);
                var rawReasons = data.verify_reasons || {};
                this.verifyReasons = {};
                for (var k in rawReasons) {
                    this.verifyReasons[parseInt(k)] = rawReasons[k];
                }
                this.glossary = data.glossary || '';
                this.speakers = data.speakers || [];
                this.speakerMap = data.speaker_map || {};
                this.renderRegions();
            } catch (e) {
                console.error(e);
            } finally {
                this.loading = false;
            }
        },

        async saveGlossary() {
            try {
                await fetch('/api/jobs/' + jobId + '/glossary', {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({glossary: this.glossary}),
                });
                this.glossarySaved = true;
                var self = this;
                setTimeout(function () { self.glossarySaved = false; }, 2000);
                this.$dispatch('glossary-saved');
            } catch (e) {
                console.error('Failed to save glossary:', e);
            }
        },
    };
}
