/** Keyboard shortcuts for SRT Editor — scope-aware keybinding registry. */

export function createKeyboardShortcuts(i18n) {
    return {
        _helpVisible: false,
        _boundHandler: null,

        initKeyboard() {
            var self = this;
            this._boundHandler = function (e) { self._handleKeydown(e); };
            document.addEventListener('keydown', this._boundHandler);
        },

        // Alpine 3.x calls destroy() automatically on component teardown.
        destroy() {
            if (this._boundHandler) {
                document.removeEventListener('keydown', this._boundHandler);
                this._boundHandler = null;
            }
        },

        getShortcutList() {
            return [
                { keys: '\u2191 / \u2193', desc: i18n.navUp + ' / ' + i18n.navDown },
                { keys: 'Enter', desc: i18n.expand },
                { keys: 'Escape', desc: i18n.collapse },
                { keys: 'Space', desc: i18n.playSegment },
                { keys: 'Shift + Space', desc: i18n.playGlobal },
                { keys: 'Ctrl/\u2318 + S', desc: i18n.save },
                { keys: 'Ctrl/\u2318 + M', desc: i18n.merge },
                { keys: 'Ctrl/\u2318 + D', desc: i18n.deleteKey },
                { keys: 'Ctrl/\u2318 + Enter', desc: i18n.suggest },
                { keys: '[ / ]', desc: i18n.nudgeBack + ' / ' + i18n.nudgeForward },
                { keys: '?', desc: i18n.help },
            ];
        },

        _handleKeydown(e) {
            var inInput = (e.target.tagName === 'TEXTAREA' || e.target.tagName === 'INPUT');
            var ctrl = e.ctrlKey || e.metaKey;

            // Ctrl combos — always active
            if (ctrl) {
                switch (e.key) {
                    case 's':
                        e.preventDefault();
                        this.saveSegments();
                        return;
                    case 'm':
                        e.preventDefault();
                        this.mergeSelected();
                        return;
                    case 'd':
                        e.preventDefault();
                        if (this.activeSegmentIdx !== null) {
                            this.deleteSegment(this.activeSegmentIdx);
                        }
                        return;
                    case 'Enter':
                        e.preventDefault();
                        if (this.activeSegmentIdx !== null) {
                            this.requestSuggestion(this.activeSegmentIdx);
                        }
                        return;
                }
            }

            // Escape — always active
            if (e.key === 'Escape') {
                e.preventDefault();
                this._helpVisible = false;
                this.activeSegmentIdx = null;
                this.selected = [];
                if (inInput) e.target.blur();
                return;
            }

            // Skip remaining shortcuts when in text fields
            if (inInput) return;

            switch (e.key) {
                case 'ArrowUp':
                    e.preventDefault();
                    this._navigateSegment(-1);
                    return;
                case 'ArrowDown':
                    e.preventDefault();
                    this._navigateSegment(1);
                    return;
                case 'Tab':
                    e.preventDefault();
                    this._navigateSegment(e.shiftKey ? -1 : 1);
                    return;
                case 'Enter':
                    e.preventDefault();
                    this._focusSegmentText();
                    return;
                case ' ':
                    e.preventDefault();
                    if (e.shiftKey) {
                        this.togglePlay();
                    } else if (this.activeSegmentIdx !== null) {
                        var seg = this.segments[this.activeSegmentIdx];
                        this.playSegment(seg.start, seg.end);
                    } else {
                        this.togglePlay();
                    }
                    return;
                case '[':
                    if (this.activeSegmentIdx !== null) {
                        this.nudgeTime(this.activeSegmentIdx, 'start', -0.1);
                    }
                    return;
                case ']':
                    if (this.activeSegmentIdx !== null) {
                        this.nudgeTime(this.activeSegmentIdx, 'end', 0.1);
                    }
                    return;
                case '?':
                    this._helpVisible = !this._helpVisible;
                    return;
            }
        },

        _navigateSegment(delta) {
            if (!this.segments.length) return;
            var current = this.activeSegmentIdx;
            var next;
            if (current === null) {
                next = delta > 0 ? 0 : this.segments.length - 1;
            } else {
                next = current + delta;
                if (next < 0) next = 0;
                if (next >= this.segments.length) next = this.segments.length - 1;
            }
            this.activeSegmentIdx = next;
            var el = document.getElementById('seg-' + next);
            if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        },

        _focusSegmentText() {
            if (this.activeSegmentIdx === null) return;
            var el = document.getElementById('seg-' + this.activeSegmentIdx);
            if (!el) return;
            var textarea = el.querySelector('textarea');
            if (textarea) textarea.focus();
        },
    };
}
