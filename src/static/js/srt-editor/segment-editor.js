/** Segment CRUD and time manipulation — uses Alpine `this`. */

import { formatTimeFull, parseTime } from './time-utils.js';

export function createSegmentEditor(jobId, i18n) {
    return {
        nudgeTime(idx, field, delta) {
            var newVal = Math.max(0, Math.round((this.segments[idx][field] + delta) * 10) / 10);
            if (field === 'end') {
                this.updateEnd(idx, formatTimeFull(newVal));
            } else {
                this.segments[idx].start = newVal;
                this.debounceSave();
            }
        },

        updateEnd(idx, value) {
            var newEnd = parseTime(value);
            if (newEnd === null) return;
            if (idx + 1 < this.segments.length && newEnd > this.segments[idx + 1].end) {
                this.segments[idx]._error = i18n.exceedsNext;
                var seg = this.segments[idx];
                setTimeout(function () { seg._error = null; }, 3000);
                return;
            }
            var oldEnd = this.segments[idx].end;
            this.segments[idx].end = newEnd;
            this.segments[idx]._error = null;
            if (idx + 1 < this.segments.length && newEnd > oldEnd) {
                this.segments[idx + 1].start = newEnd;
            }
            this.debounceSave();
        },

        _clearSuggestions() {
            this.suggestions = {};
            this.suggesting = {};
        },

        deleteSegment(idx) {
            if (!confirm(i18n.deleteConfirm)) return;
            this.segments.splice(idx, 1);
            this.selected = this.selected.filter(function (i) { return i !== idx; }).map(function (i) { return i > idx ? i - 1 : i; });
            this._clearSuggestions();
            this.debounceSave();
        },

        addSegmentAfter(idx) {
            var prev = this.segments[idx];
            var next = this.segments[idx + 1];
            var start = prev.end;
            var end = next ? next.start : prev.end + 2.0;
            this.segments.splice(idx + 1, 0, { start: start, end: end, text: '' });
            this._clearSuggestions();
            this.debounceSave();
        },

        mergeSelected() {
            if (this.selected.length < 2) return;
            var sorted = [].concat(this.selected).sort(function (a, b) { return a - b; });
            for (var i = 1; i < sorted.length; i++) {
                if (sorted[i] !== sorted[i - 1] + 1) {
                    showToast(i18n.mergeConsecutiveOnly, 'warning');
                    return;
                }
            }
            var first = sorted[0];
            var last = sorted[sorted.length - 1];
            var segs = this.segments;
            var merged = {
                start: segs[first].start,
                end: segs[last].end,
                text: sorted.map(function (i) { return segs[i].text; }).join(' '),
            };
            this.segments.splice(first, sorted.length, merged);
            this.selected = [];
            this._clearSuggestions();
            this.debounceSave();
        },
    };
}
