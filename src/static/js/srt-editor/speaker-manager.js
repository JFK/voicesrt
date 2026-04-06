/** Speaker management — CRUD, color assignment, persistence. */

var SPEAKER_COLORS = [
    {bg: 'bg-blue-100', text: 'text-blue-800', border: 'border-blue-300', dot: 'bg-blue-500'},
    {bg: 'bg-rose-100', text: 'text-rose-800', border: 'border-rose-300', dot: 'bg-rose-500'},
    {bg: 'bg-emerald-100', text: 'text-emerald-800', border: 'border-emerald-300', dot: 'bg-emerald-500'},
    {bg: 'bg-amber-100', text: 'text-amber-800', border: 'border-amber-300', dot: 'bg-amber-500'},
    {bg: 'bg-purple-100', text: 'text-purple-800', border: 'border-purple-300', dot: 'bg-purple-500'},
    {bg: 'bg-cyan-100', text: 'text-cyan-800', border: 'border-cyan-300', dot: 'bg-cyan-500'},
    {bg: 'bg-orange-100', text: 'text-orange-800', border: 'border-orange-300', dot: 'bg-orange-500'},
    {bg: 'bg-teal-100', text: 'text-teal-800', border: 'border-teal-300', dot: 'bg-teal-500'},
];

export { SPEAKER_COLORS };

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
        },

        setSpeaker(idx, speaker) {
            if (speaker) {
                this.speakerMap = Object.assign({}, this.speakerMap, {[idx]: speaker});
            } else {
                var m = Object.assign({}, this.speakerMap);
                delete m[idx];
                this.speakerMap = m;
            }
            this._debounceSaveSpeakers();
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
