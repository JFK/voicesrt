/** Speaker management — CRUD, color assignment, persistence. */

// Each speaker palette entry carries the Tailwind classes used by badges,
// dots, and borders, plus the RGBA `tint` used to paint waveform segment
// regions. Keeping all variants on one object prevents drift between
// the editor UI and the waveform visualization.
var SPEAKER_COLORS = [
    {bg: 'bg-blue-100', text: 'text-blue-800', border: 'border-blue-300', dot: 'bg-blue-500', tint: 'rgba(59, 130, 246, 0.18)'},
    {bg: 'bg-rose-100', text: 'text-rose-800', border: 'border-rose-300', dot: 'bg-rose-500', tint: 'rgba(244, 63, 94, 0.18)'},
    {bg: 'bg-emerald-100', text: 'text-emerald-800', border: 'border-emerald-300', dot: 'bg-emerald-500', tint: 'rgba(16, 185, 129, 0.18)'},
    {bg: 'bg-amber-100', text: 'text-amber-800', border: 'border-amber-300', dot: 'bg-amber-500', tint: 'rgba(245, 158, 11, 0.18)'},
    {bg: 'bg-purple-100', text: 'text-purple-800', border: 'border-purple-300', dot: 'bg-purple-500', tint: 'rgba(168, 85, 247, 0.18)'},
    {bg: 'bg-cyan-100', text: 'text-cyan-800', border: 'border-cyan-300', dot: 'bg-cyan-500', tint: 'rgba(6, 182, 212, 0.18)'},
    {bg: 'bg-orange-100', text: 'text-orange-800', border: 'border-orange-300', dot: 'bg-orange-500', tint: 'rgba(249, 115, 22, 0.18)'},
    {bg: 'bg-teal-100', text: 'text-teal-800', border: 'border-teal-300', dot: 'bg-teal-500', tint: 'rgba(20, 184, 166, 0.18)'},
];

export { SPEAKER_COLORS };

export var UNASSIGNED_SPEAKER_TINT = 'rgba(148, 163, 184, 0.10)'; // slate-400 @ 10%

export function createSpeakerManager(jobId) {
    return {
        speakerColors: SPEAKER_COLORS,

        getSpeakerColor(speaker) {
            var i = this.speakers.indexOf(speaker);
            if (i < 0) return SPEAKER_COLORS[0];
            return SPEAKER_COLORS[i % SPEAKER_COLORS.length];
        },

        addSpeaker() {
            var name = this.speakerInput.trim();
            if (name && !this.speakers.includes(name)) {
                this.speakers.push(name);
                this.speakerInput = '';
            }
        },

        removeSpeaker(i) {
            var removed = this.speakers[i];
            this.speakers.splice(i, 1);
            for (var k in this.speakerMap) {
                if (this.speakerMap[k] === removed) delete this.speakerMap[k];
            }
            this.renderRegions();
        },

        setSpeaker(idx, speaker) {
            if (speaker) {
                this.speakerMap = Object.assign({}, this.speakerMap, {[idx]: speaker});
            } else {
                var m = Object.assign({}, this.speakerMap);
                delete m[idx];
                this.speakerMap = m;
            }
            this.renderRegions();
            this._debounceSaveSpeakers();
        },

        // Reindex speakerMap after a segment-array mutation. `remap` receives
        // the old segment index and returns the new index, or null to drop
        // the mapping. Used by add/delete/merge in segment-editor so speakers
        // stay anchored to their original segments after structural edits.
        _remapSpeakers(remap) {
            var next = {};
            for (var k in this.speakerMap) {
                var newIdx = remap(parseInt(k, 10));
                if (newIdx !== null && newIdx !== undefined) {
                    next[newIdx] = this.speakerMap[k];
                }
            }
            this.speakerMap = next;
        },

        _debounceSaveSpeakers() {
            if (this._speakerTimer) clearTimeout(this._speakerTimer);
            var self = this;
            this._speakerTimer = setTimeout(function () { self.saveSpeakers(); }, 500);
        },

        async saveSpeakers() {
            try {
                await fetch('/api/jobs/' + jobId + '/speakers', {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({speakers: this.speakers, speaker_map: this.speakerMap}),
                });
                this.$dispatch('speakers-saved');
            } catch (e) {
                console.error('Failed to save speakers:', e);
            }
        },
    };
}
