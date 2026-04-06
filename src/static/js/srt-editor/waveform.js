/** Waveform visualization — wavesurfer.js v7 with segment regions and theme sync. */

import WaveSurfer from 'https://unpkg.com/wavesurfer.js@7.8.6/dist/wavesurfer.esm.js';
import RegionsPlugin from 'https://unpkg.com/wavesurfer.js@7.8.6/dist/plugins/regions.esm.js';

// Tailwind class → RGBA tint used to paint segment regions on the waveform.
// Mirrors the speaker palette in speaker-manager.js so dots, badges, and
// regions all read as the same speaker.
var REGION_TINTS = {
    'bg-blue-100': 'rgba(59, 130, 246, 0.18)',
    'bg-rose-100': 'rgba(244, 63, 94, 0.18)',
    'bg-emerald-100': 'rgba(16, 185, 129, 0.18)',
    'bg-amber-100': 'rgba(245, 158, 11, 0.18)',
    'bg-purple-100': 'rgba(168, 85, 247, 0.18)',
    'bg-cyan-100': 'rgba(6, 182, 212, 0.18)',
    'bg-orange-100': 'rgba(249, 115, 22, 0.18)',
    'bg-teal-100': 'rgba(20, 184, 166, 0.18)',
};
var UNASSIGNED_TINT = 'rgba(148, 163, 184, 0.10)'; // slate-400 @ 10%

// Module-level holders for the wavesurfer instance and its regions plugin.
// IMPORTANT: storing these on Alpine `this` would wrap them in Alpine's
// reactive Proxy, which breaks wavesurfer's internal mutation of region
// DOM elements (clearRegions crashes with "Cannot read properties of null").
// One SRT editor per page, so a module-level singleton is safe.
var _ws = null;
var _regions = null;
var _wsReady = false;
var _themeObserver = null;

function themeColors() {
    var dark = document.documentElement.classList.contains('dark');
    return dark
        ? { wave: '#475569', progress: '#60a5fa', cursor: '#f1f5f9' }
        : { wave: '#cbd5e1', progress: '#3b82f6', cursor: '#1e293b' };
}

function observeTheme() {
    if (_themeObserver) return;
    _themeObserver = new MutationObserver(function () {
        if (!_ws) return;
        var c = themeColors();
        _ws.setOptions({ waveColor: c.wave, progressColor: c.progress, cursorColor: c.cursor });
    });
    _themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
}

export function createWaveformController() {
    return {
        initWaveform() {
            if (_ws) return;
            var container = this.$refs.waveform;
            var audio = this.$refs.audio;
            if (!container || !audio) return;
            var colors = themeColors();
            _regions = RegionsPlugin.create();
            _ws = WaveSurfer.create({
                container: container,
                media: audio,
                height: 60,
                waveColor: colors.wave,
                progressColor: colors.progress,
                cursorColor: colors.cursor,
                cursorWidth: 2,
                barWidth: 2,
                barGap: 1,
                barRadius: 2,
                normalize: true,
                interact: true,
                plugins: [_regions],
            });
            var self = this;
            _ws.on('ready', function () {
                _wsReady = true;
                self.renderRegions();
            });
            observeTheme();
        },

        renderRegions() {
            // Skip until wavesurfer has decoded; addRegion before 'ready'
            // produces queued regions with null DOM elements that crash
            // subsequent clearRegions().
            if (!_regions || !_wsReady) return;
            _regions.clearRegions();
            var self = this;
            this.segments.forEach(function (seg, i) {
                _regions.addRegion({
                    start: seg.start,
                    end: seg.end,
                    color: self._regionColor(self.speakerMap[i]),
                    drag: false,
                    resize: false,
                });
            });
        },

        _regionColor(speaker) {
            if (!speaker) return UNASSIGNED_TINT;
            var c = this.getSpeakerColor(speaker);
            return REGION_TINTS[c.bg] || UNASSIGNED_TINT;
        },

        destroyWaveform() {
            if (_ws) {
                _ws.destroy();
                _ws = null;
                _regions = null;
                _wsReady = false;
            }
            if (_themeObserver) {
                _themeObserver.disconnect();
                _themeObserver = null;
            }
        },
    };
}
