/** Segment CRUD and time manipulation — uses Alpine `this`. */

import { formatTimeFull, parseTime } from './time-utils.js';
import { nextSegmentUid } from './save-manager.js';

export function createSegmentEditor(i18n) {
    return {
        nudgeTime(idx, field, delta) {
            var newVal = Math.max(0, Math.round((this.segments[idx][field] + delta) * 10) / 10);
            if (field === 'end') this.updateEnd(idx, formatTimeFull(newVal));
            else this.updateStart(idx, formatTimeFull(newVal));
        },

        _flashError(idx, msg) {
            var seg = this.segments[idx];
            seg._error = msg;
            setTimeout(function () { seg._error = null; }, 3000);
        },

        updateEnd(idx, value) {
            var newEnd = parseTime(value);
            if (newEnd === null) return;
            if (idx + 1 < this.segments.length && newEnd > this.segments[idx + 1].end) {
                this._flashError(idx, i18n.exceedsNext);
                return;
            }
            var seg = this.segments[idx];
            var oldEnd = seg.end;
            seg.end = newEnd;
            if (seg._error) seg._error = null;
            if (idx + 1 < this.segments.length && newEnd > oldEnd) {
                this.segments[idx + 1].start = newEnd;
            }
            this.renderRegions();
            this.debounceSave();
        },

        updateStart(idx, value) {
            var newStart = parseTime(value);
            if (newStart === null) return;
            // Reject overlap with the previous segment or with own end so a
            // rapid − nudge cannot silently poison subsequent saves with a
            // server-side validation failure.
            var seg = this.segments[idx];
            var overlapsPrev = idx > 0 && newStart < this.segments[idx - 1].end;
            var breaksOwnRange = newStart >= seg.end;
            if (overlapsPrev || breaksOwnRange) {
                this._flashError(idx, i18n.precedesPrev);
                return;
            }
            seg.start = newStart;
            if (seg._error) seg._error = null;
            this.renderRegions();
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
            this._remapSpeakers(function (i) {
                if (i === idx) return null;
                return i > idx ? i - 1 : i;
            });
            this._clearSuggestions();
            this.renderRegions();
            this.debounceSave();
        },

        addSegmentAfter(idx) {
            var prev = this.segments[idx];
            var next = this.segments[idx + 1];
            var start = prev.end;
            var end = next ? next.start : prev.end + 2.0;
            this.segments.splice(idx + 1, 0, { start: start, end: end, text: '', _uid: nextSegmentUid() });
            this._remapSpeakers(function (i) {
                return i > idx ? i + 1 : i;
            });
            this._clearSuggestions();
            this.renderRegions();
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
                _uid: nextSegmentUid(),
            };
            this.segments.splice(first, sorted.length, merged);
            // The merged segment keeps the first segment's speaker; the
            // remaining merged indices drop their mappings, and any later
            // segments shift down by (sorted.length - 1).
            var mergedCount = sorted.length;
            this._remapSpeakers(function (i) {
                if (i === first) return first;
                if (i > first && i <= last) return null;
                if (i > last) return i - (mergedCount - 1);
                return i;
            });
            this.selected = [];
            this._clearSuggestions();
            this.renderRegions();
            this.debounceSave();
        },
    };
}
