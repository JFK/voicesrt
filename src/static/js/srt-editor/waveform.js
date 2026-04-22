/** Waveform visualization — wavesurfer.js v7 with segment regions and theme sync. */

import WaveSurfer from 'https://unpkg.com/wavesurfer.js@7.8.6/dist/wavesurfer.esm.js';
import RegionsPlugin from 'https://unpkg.com/wavesurfer.js@7.8.6/dist/plugins/regions.esm.js';
import { UNASSIGNED_SPEAKER_TINT } from './speaker-manager.js';

// Module-level holders for the wavesurfer instance and its regions plugin.
// IMPORTANT: storing these on Alpine `this` would wrap them in Alpine's
// reactive Proxy, which breaks wavesurfer's internal mutation of region
// DOM elements (clearRegions crashes with "Cannot read properties of null").
// One SRT editor per page, so a module-level singleton is safe.
var _ws = null;
var _regions = null;
var _wsReady = false;
var _themeObserver = null;
var _renderRaf = 0;
// uid → wavesurfer Region handle. In-place updates only; clearRegions() and
// region.remove() leak DOM nodes during playback.
var _regionByUid = Object.create(null);

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
                self._waveformReady = true;
                self.renderRegions();
            });
            observeTheme();
        },

        renderRegions() {
            // addRegion before 'ready' leaves queued regions with null DOM
            // elements that crash a subsequent clearRegions().
            if (!_regions || !_wsReady) return;
            if (_renderRaf) return;
            var self = this;
            _renderRaf = requestAnimationFrame(function () {
                _renderRaf = 0;
                if (!_regions || !_wsReady) return;
                var present = Object.create(null);
                self.segments.forEach(function (seg, i) {
                    var uid = seg._uid;
                    present[uid] = true;
                    var color = self._regionColor(self.speakerMap[i]);
                    var region = _regionByUid[uid];
                    if (region) {
                        region.setOptions({ start: seg.start, end: seg.end, color: color });
                    } else {
                        _regionByUid[uid] = _regions.addRegion({
                            start: seg.start,
                            end: seg.end,
                            color: color,
                            drag: false,
                            resize: false,
                        });
                    }
                });
                for (var uid in _regionByUid) {
                    if (!present[uid]) {
                        _regionByUid[uid].remove();
                        delete _regionByUid[uid];
                    }
                }
            });
        },

        _regionColor(speaker) {
            if (!speaker) return UNASSIGNED_SPEAKER_TINT;
            return this.getSpeakerColor(speaker).tint || UNASSIGNED_SPEAKER_TINT;
        },

        destroyWaveform() {
            if (_renderRaf) {
                cancelAnimationFrame(_renderRaf);
                _renderRaf = 0;
            }
            _regionByUid = Object.create(null);
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
