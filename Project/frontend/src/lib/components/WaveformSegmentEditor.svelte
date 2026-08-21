<script>
	import { onMount } from 'svelte';

	import { normalizeWaveformRange } from '$lib/utils/waveform.js';

	let {
		media,
		audioUrl = '',
		durationMs = 0,
		startMs = 0,
		endMs = 0,
		currentTimeMs = 0,
		minDurationMs = 500,
		maxDurationMs = 300_000,
		analysisMarkers = [],
		disabled = false,
		onStartChange = () => {},
		onEndChange = () => {},
		onSeek = () => {},
		onReady = () => {},
		onError = () => {}
	} = $props();

	/** @typedef {{kind:string,startMs:number,endMs?:number,label?:string}} AnalysisMarker */
	/** @type {HTMLDivElement|undefined} */
	let container;
	let mounted = $state(false);
	let status = $state('idle');
	let loadingPercent = $state(0);
	let errorMessage = $state('');
	let ready = $state(false);
	/** @type {any} */
	let wave = null;
	/** @type {any} */
	let regions = null;
	/** @type {any} */
	let selectionRegion = null;
	/** @type {any[]} */
	let markerRegions = [];
	let generation = 0;
	let syncingRegion = false;
	let effectiveDurationMs = 0;

	onMount(() => {
		mounted = true;
		return () => {
			mounted = false;
			destroyWaveform();
		};
	});

	$effect(() => {
		const host = container;
		const player = media;
		const url = audioUrl;
		const trackDuration = Number(durationMs) || 0;
		const isDisabled = disabled;
		if (!mounted || !host || !player || !url || isDisabled) {
			destroyWaveform();
			status = isDisabled ? 'disabled' : 'idle';
			return;
		}

		destroyWaveform();
		const token = ++generation;
		void initializeWaveform(token, host, player, url, trackDuration);
		return () => {
			if (token === generation) destroyWaveform();
		};
	});

	$effect(() => {
		const nextStart = Number(startMs) || 0;
		const nextEnd = Number(endMs) || 0;
		const minimum = Number(minDurationMs) || 1;
		const maximum = Number(maxDurationMs) || Number(durationMs) || 1;
		const markers = analysisMarkers;
		if (ready) syncRegions(nextStart, nextEnd, minimum, maximum, markers);
	});

	$effect(() => {
		const cursorMs = Number(currentTimeMs) || 0;
		if (!ready || !wave || !media || media.seeking) return;
		if (Math.abs(media.currentTime * 1000 - cursorMs) > 120) wave.setTime(cursorMs / 1000);
	});

	function destroyWaveform() {
		generation += 1;
		ready = false;
		selectionRegion = null;
		markerRegions = [];
		regions = null;
		if (wave) {
			wave.destroy();
			wave = null;
		}
	}

	/**
	 * @param {number} token
	 * @param {HTMLDivElement} host
	 * @param {HTMLAudioElement} player
	 * @param {string} url
	 * @param {number} trackDuration
	 */
	async function initializeWaveform(token, host, player, url, trackDuration) {
		status = 'loading';
		loadingPercent = 0;
		errorMessage = '';
		try {
			const [{ default: WaveSurfer }, { default: RegionsPlugin }] = await Promise.all([
				import('wavesurfer.js'),
				import('wavesurfer.js/dist/plugins/regions.esm.js')
			]);
			if (!mounted || token !== generation || !host) return;

			const regionPlugin = RegionsPlugin.create();
			const instance = WaveSurfer.create({
				container: host,
				media: player,
				url,
				height: 112,
				waveColor: '#355071',
				progressColor: '#64e0c1',
				cursorColor: '#f7c873',
				cursorWidth: 2,
				barWidth: 2,
				barGap: 1,
				barRadius: 2,
				normalize: true,
				interact: true,
				dragToSeek: true,
				autoScroll: false,
				plugins: [regionPlugin]
			});
			if (!mounted || token !== generation) {
				instance.destroy();
				return;
			}
			wave = instance;
			regions = regionPlugin;

			instance.on('loading', (percent) => {
				loadingPercent = Math.round(percent);
			});
			instance.on('ready', (decodedDuration) => {
				effectiveDurationMs = Math.round((decodedDuration || trackDuration / 1000) * 1000);
				ready = true;
				status = 'ready';
				syncRegions(startMs, endMs, minDurationMs, maxDurationMs, analysisMarkers);
				onReady();
			});
			instance.on('interaction', (seconds) => onSeek(Math.round(seconds * 1000)));
			instance.on('error', (waveError) => handleWaveformError(waveError));
			regionPlugin.on('region-update', handleRegionUpdate);
			regionPlugin.on('region-updated', handleRegionUpdate);
		} catch (waveError) {
			handleWaveformError(waveError);
		}
	}

	/** @param {unknown} waveError */
	function handleWaveformError(waveError) {
		status = 'error';
		errorMessage = waveError instanceof Error ? waveError.message : 'Waveform could not be loaded.';
		onError(errorMessage);
	}

	/** @param {any} region */
	function handleRegionUpdate(region) {
		if (syncingRegion || region !== selectionRegion) return;
		const rawStart = Math.round(region.start * 1000);
		const rawEnd = Math.round(region.end * 1000);
		const startMoved = Math.abs(rawStart - Number(startMs)) >= Math.abs(rawEnd - Number(endMs));
		const normalized = normalizeWaveformRange(
			rawStart,
			rawEnd,
			effectiveDurationMs || durationMs,
			minDurationMs,
			maxDurationMs,
			startMoved ? 'start' : 'end'
		);
		if (normalized.startMs !== rawStart || normalized.endMs !== rawEnd) {
			syncingRegion = true;
			region.setOptions({ start: normalized.startMs / 1000, end: normalized.endMs / 1000 });
			syncingRegion = false;
		}
		if (normalized.startMs !== Number(startMs)) onStartChange(normalized.startMs);
		if (normalized.endMs !== Number(endMs)) onEndChange(normalized.endMs);
	}

	/**
	 * @param {number} nextStart
	 * @param {number} nextEnd
	 * @param {number} minimum
	 * @param {number} maximum
	 * @param {AnalysisMarker[]} markers
	 */
	function syncRegions(nextStart, nextEnd, minimum, maximum, markers) {
		if (!regions) return;
		const trackDuration = effectiveDurationMs || Number(durationMs) || 0;
		const normalized = normalizeWaveformRange(nextStart, nextEnd, trackDuration, minimum, maximum);

		syncingRegion = true;
		if (!selectionRegion) {
			selectionRegion = regions.addRegion({
				id: 'user-selection',
				start: normalized.startMs / 1000,
				end: normalized.endMs / 1000,
				color: 'rgba(80, 224, 190, 0.24)',
				drag: !disabled,
				resize: !disabled,
				minLength: Math.min(trackDuration, minimum) / 1000,
				maxLength: Math.min(trackDuration, maximum) / 1000
			});
		} else {
			selectionRegion.setOptions({
				start: normalized.startMs / 1000,
				end: normalized.endMs / 1000,
				drag: !disabled,
				resize: !disabled
			});
		}

		for (const region of markerRegions) region.remove();
		markerRegions = [];
		for (const marker of markers || []) {
			const markerStart = Math.max(0, Math.min(trackDuration, Number(marker.startMs) || 0));
			const markerEnd = Math.max(
				markerStart + 1,
				Math.min(
					trackDuration,
					Number(marker.endMs) || markerStart + Math.max(20, trackDuration / 500)
				)
			);
			markerRegions.push(
				regions.addRegion({
					id: marker.kind === 'phrase' ? 'phrase-marker' : `${marker.kind || 'analysis'}-marker`,
					start: markerStart / 1000,
					end: markerEnd / 1000,
					color: markerColor(marker.kind),
					drag: false,
					resize: false,
					content: marker.label || ''
				})
			);
		}
		syncingRegion = false;
	}

	/** @param {string} kind */
	function markerColor(kind) {
		if (kind === 'ai') return 'rgba(247, 188, 92, 0.27)';
		if (kind === 'phrase') return 'rgba(119, 156, 255, 0.52)';
		if (kind === 'invalid') return 'rgba(255, 91, 123, 0.34)';
		return 'rgba(84, 139, 255, 0.2)';
	}
</script>

<section
	class="waveform-editor"
	data-testid="studio-waveform"
	data-status={status}
	aria-label="Waveform segment editor"
>
	<div class="legend" aria-hidden="true">
		<span class="selected">Selection</span><span class="highlight">Detected highlight</span><span
			class="phrase">Phrase</span
		><span class="ai">AI suggestion</span>
	</div>
	<div bind:this={container} class="waveform" data-testid="waveform-canvas"></div>
	{#if status === 'loading'}
		<div class="waveform-state" data-testid="waveform-status" aria-live="polite">
			Loading waveform… {loadingPercent}%
		</div>
	{:else if status === 'error'}
		<div class="waveform-state error" data-testid="waveform-status" role="alert">
			Waveform unavailable. Use the exact numeric controls below. {errorMessage}
		</div>
	{:else if status === 'disabled'}
		<div class="waveform-state" data-testid="waveform-status">Waveform editing is disabled.</div>
	{/if}
	<span
		class="sr-only"
		data-testid="waveform-selection"
		data-start-ms={Math.round(Number(startMs) || 0)}
		data-end-ms={Math.round(Number(endMs) || 0)}
	>
		Selection from {Math.round(Number(startMs) || 0)} to {Math.round(Number(endMs) || 0)}
		milliseconds
	</span>
</section>

<style>
	.waveform-editor {
		position: relative;
		min-height: 148px;
		margin: 10px 0 14px;
		padding: 10px;
		border: 1px solid #243a58;
		border-radius: 14px;
		background: #07111f;
		overflow: hidden;
	}
	.legend {
		display: flex;
		flex-wrap: wrap;
		gap: 9px;
		margin-bottom: 8px;
		color: #8095b2;
		font-size: 9px;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}
	.legend span::before {
		content: '';
		display: inline-block;
		width: 7px;
		height: 7px;
		margin-right: 4px;
		border-radius: 2px;
	}
	.legend .selected::before {
		background: #50e0be;
	}
	.legend .highlight::before {
		background: #548bff;
	}
	.legend .phrase::before {
		background: #779cff;
	}
	.legend .ai::before {
		background: #f7bc5c;
	}
	.waveform {
		min-height: 112px;
		cursor: crosshair;
	}
	.waveform::part(user-selection) {
		border-inline: 2px solid #64e0c1;
		z-index: 10;
	}
	.waveform::part(region-handle-left),
	.waveform::part(region-handle-right) {
		width: 12px !important;
		background: rgba(100, 224, 193, 0.88) !important;
	}
	.waveform::part(phrase-marker) {
		min-width: 2px;
	}
	.waveform-state {
		position: absolute;
		inset: 36px 10px 10px;
		display: grid;
		place-items: center;
		padding: 12px;
		background: rgba(7, 17, 31, 0.88);
		color: #8fa5c2;
		font-size: 12px;
		text-align: center;
	}
	.waveform-state.error {
		color: #ffadbd;
	}
	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		white-space: nowrap;
		border: 0;
	}
	@media (max-width: 720px) {
		.waveform-editor {
			min-height: 132px;
		}
		.waveform {
			min-height: 96px;
		}
		.legend .phrase {
			display: none;
		}
	}
</style>
