<script>
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { tick } from 'svelte';

	import AutoMixModeSelector from '$lib/components/AutoMixModeSelector.svelte';
	import WaveformSegmentEditor from '$lib/components/WaveformSegmentEditor.svelte';
	import {
		addSegmentToMix,
		autoMixFromSaved,
		chatWithStudioAssistant,
		createSavedSegment,
		createStudioMix,
		deleteSavedSegment,
		duplicateStudioMix,
		listSavedSegments,
		listStudioMixes,
		previewStudioTransition,
		publishStudioMix,
		recordStudioBehavior,
		removeMixItem,
		renderStudioMix,
		reorderStudioMix,
		searchStudioTracks,
		updateSavedSegment,
		updateStudioMix,
		updateStudioTransition
	} from '$lib/services/studioApi.js';
	import { authStore } from '$lib/stores/authStore.js';
	import { normalizeWaveformRange } from '$lib/utils/waveform.js';

	let loaded = $state(false);
	let busy = $state('');
	let error = $state('');
	let notice = $state('');
	let searchQuery = $state('');
	/** @type {'all'|'catalog'|'audius'} */
	let sourceFilter = $state('all');
	/** @type {import('$lib/types.js').StudioTrack[]} */
	let tracks = $state([]);
	/** @type {import('$lib/types.js').StudioTrack|null} */
	let selectedTrack = $state(null);
	let segmentFilter = $state('');
	/** @type {import('$lib/types.js').SavedSegment[]} */
	let savedSegments = $state([]);
	/** @type {import('$lib/types.js').Mix[]} */
	let mixes = $state([]);
	let activeMixId = $state(0);
	let newMixTitle = $state('My Studio mix');
	let autoMixTitle = $state('Saved moments flow');
	let autoPrompt = $state('Build a coherent mix from my saved moments');
	/** @type {import('$lib/types.js').AutoMixMode|null} */
	let autoMode = $state(null);

	/** @type {HTMLAudioElement|undefined} */
	let audioElement = $state();
	let previewUrl = $state('');
	let previewStartMs = $state(0);
	let previewEndMs = $state(0);
	let currentMs = $state(0);
	let loopPreview = $state(false);
	let startSeconds = $state(0);
	let endSeconds = $state(30);
	let segmentLabel = $state('Favorite moment');

	let assistantOpen = $state(true);
	let assistantInput = $state('');
	/** @type {{role:'user'|'assistant',content:string}[]} */
	let assistantMessages = $state([]);
	/** @type {import('$lib/types.js').StudioAssistantRecommendation|null} */
	let recommendation = $state(null);
	let compareNextAi = $state(true);
	/** @type {number|null} */
	let activeSavedSegmentId = $state(null);
	/** @type {number|null} */
	let skipReportedSegmentId = $state(null);

	let activeMix = $derived(mixes.find((mix) => mix.id === activeMixId) || null);
	let filteredSegments = $derived(
		savedSegments.filter((segment) => {
			const query = segmentFilter.trim().toLowerCase();
			return (
				!query ||
				segment.label.toLowerCase().includes(query) ||
				segment.title.toLowerCase().includes(query) ||
				segment.artist.toLowerCase().includes(query)
			);
		})
	);
	let selectionDurationMs = $derived(Math.max(0, Math.round((endSeconds - startSeconds) * 1000)));
	let editingSelectedTrack = $derived(
		Boolean(
			selectedTrack &&
			previewUrl &&
			previewUrl === /** @type {import('$lib/types.js').StudioTrack} */ (selectedTrack).audioUrl
		)
	);
	let waveformMarkers = $derived(buildWaveformMarkers());

	$effect(() => {
		if ($authStore.status === 'guest') void goto(resolve('/login'));
		if ($authStore.status === 'authenticated' && !loaded) {
			loaded = true;
			void loadWorkspace();
		}
	});

	async function loadWorkspace() {
		busy = 'loading';
		error = '';
		try {
			[savedSegments, mixes] = await Promise.all([listSavedSegments(), listStudioMixes()]);
			if (!activeMixId && mixes.length) activeMixId = mixes[0].id;
			await runSearch();
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not load Studio.';
		} finally {
			busy = '';
		}
	}

	async function runSearch() {
		busy = 'search';
		error = '';
		try {
			tracks = await searchStudioTracks(searchQuery.trim(), sourceFilter);
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Search failed.';
		} finally {
			busy = '';
		}
	}

	/** @param {import('$lib/types.js').StudioTrack} track */
	async function chooseTrack(track) {
		selectedTrack = track;
		activeSavedSegmentId = null;
		setSelectionMs(
			track.suggestedStartMs || 0,
			track.suggestedEndMs || Math.min(track.durationMs, 30_000)
		);
		segmentLabel = `${track.title} moment`;
		await cueAudio(
			track.audioUrl,
			Math.round(startSeconds * 1000),
			Math.round(endSeconds * 1000),
			false
		);
	}

	/** @param {string} url @param {number} startMs @param {number} endMs @param {boolean} [autoplay] */
	async function cueAudio(url, startMs, endMs, autoplay = true) {
		previewUrl = url;
		previewStartMs = startMs;
		previewEndMs = endMs;
		await tick();
		if (!audioElement) return;
		audioElement.currentTime = startMs / 1000;
		currentMs = startMs;
		if (autoplay) {
			try {
				await audioElement.play();
			} catch {
				notice = 'Press play in the audio control to start preview.';
			}
		}
	}

	function handleTimeUpdate() {
		if (!audioElement) return;
		currentMs = Math.round(audioElement.currentTime * 1000);
		if (previewEndMs && currentMs >= previewEndMs) {
			if (loopPreview) {
				audioElement.currentTime = previewStartMs / 1000;
				void audioElement.play();
			} else {
				audioElement.pause();
			}
		}
	}

	function setStartHere() {
		setSelectionMs(currentMs, Math.round(endSeconds * 1000), 'start');
	}

	function setEndHere() {
		setSelectionMs(Math.round(startSeconds * 1000), currentMs, 'end');
	}

	/** @param {number} startMs @param {number} endMs @param {'start'|'end'|'range'} [anchor] */
	function setSelectionMs(startMs, endMs, anchor = 'range') {
		const duration = selectedTrack?.durationMs || Math.max(startMs, endMs, 1);
		const normalized = normalizeWaveformRange(
			startMs,
			endMs,
			duration,
			selectedTrack?.minSegmentMs || 1000,
			selectedTrack?.maxSegmentMs || duration,
			anchor
		);
		startSeconds = normalized.startMs / 1000;
		endSeconds = normalized.endMs / 1000;
		if (selectedTrack && previewUrl === selectedTrack.audioUrl) {
			previewStartMs = normalized.startMs;
			previewEndMs = normalized.endMs;
		}
	}

	/** @param {number} positionMs */
	function seekFromWaveform(positionMs) {
		if (!audioElement) return;
		const bounded = Math.max(0, Math.min(selectedTrack?.durationMs || positionMs, positionMs));
		audioElement.currentTime = bounded / 1000;
		currentMs = bounded;
	}

	function buildWaveformMarkers() {
		if (!selectedTrack) return [];
		/** @type {{kind:string,startMs:number,endMs?:number,label:string}[]} */
		const markers = (selectedTrack.phraseBoundariesMs || []).map((value) => ({
			kind: 'phrase',
			startMs: value,
			label: ''
		}));
		if (
			selectedTrack.suggestedStartMs != null &&
			selectedTrack.suggestedEndMs != null &&
			selectedTrack.suggestedEndMs > selectedTrack.suggestedStartMs
		) {
			markers.push({
				kind: 'highlight',
				startMs: selectedTrack.suggestedStartMs,
				endMs: selectedTrack.suggestedEndMs,
				label: 'Detected highlight'
			});
		}
		const recommendationCandidateId = recommendation?.candidate_id;
		const candidate = recommendationCandidateId
			? savedSegments.find((segment) => segment.id === recommendationCandidateId)
			: null;
		if (
			candidate &&
			candidate.sourceType === selectedTrack.sourceType &&
			candidate.sourceTrackId === selectedTrack.sourceTrackId &&
			recommendation?.proposed_start_ms != null &&
			recommendation?.proposed_end_ms != null
		) {
			markers.push({
				kind: 'ai',
				startMs: recommendation.proposed_start_ms,
				endMs: recommendation.proposed_end_ms,
				label: 'AI suggestion'
			});
		}
		return markers;
	}

	/** @param {number} value */
	function handleWaveformStart(value) {
		setSelectionMs(value, Math.round(endSeconds * 1000), 'start');
	}

	/** @param {number} value */
	function handleWaveformEnd(value) {
		setSelectionMs(Math.round(startSeconds * 1000), value, 'end');
	}

	async function saveSelection() {
		if (!selectedTrack || busy) return;
		busy = 'save-segment';
		error = '';
		try {
			const saved = await createSavedSegment({
				sourceType: selectedTrack.sourceType,
				sourceTrackId: selectedTrack.sourceTrackId,
				startMs: Math.round(startSeconds * 1000),
				endMs: Math.round(endSeconds * 1000),
				label: segmentLabel.trim(),
				createdFrom: 'manual'
			});
			savedSegments = [saved, ...savedSegments];
			notice = 'Segment saved to your personal library.';
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not save segment.';
		} finally {
			busy = '';
		}
	}

	/**
	 * @param {import('$lib/types.js').SavedSegment} segment
	 * @param {boolean} [replay]
	 * @param {boolean} [autoplay]
	 */
	async function previewSaved(segment, replay = false, autoplay = true) {
		activeSavedSegmentId = segment.id;
		skipReportedSegmentId = null;
		const knownTrack = tracks.find(
			(track) =>
				track.sourceType === segment.sourceType && track.sourceTrackId === segment.sourceTrackId
		);
		selectedTrack =
			knownTrack ||
			/** @type {import('$lib/types.js').StudioTrack} */ ({
				sourceType: segment.sourceType,
				sourceTrackId: segment.sourceTrackId,
				title: segment.title,
				artist: segment.artist,
				album: segment.album,
				genre: segment.genre,
				vibe: segment.vibe,
				durationMs: segment.trackDurationMs,
				audioUrl: segment.sourceAudioUrl,
				coverUrl: segment.coverUrl,
				analysisStatus: null,
				suggestedStartMs: null,
				suggestedEndMs: null,
				phraseBoundariesMs: [],
				minSegmentMs: 1000,
				maxSegmentMs: Math.min(300000, segment.trackDurationMs),
				bpm: segment.bpm,
				musicalKey: segment.musicalKey,
				camelot: segment.camelot
			});
		setSelectionMs(segment.startMs, segment.endMs);
		segmentLabel = segment.label;
		await cueAudio(segment.sourceAudioUrl, segment.startMs, segment.endMs, autoplay);
		if (replay) void recordStudioBehavior('segment_replay', segment.id).catch(() => {});
	}

	function handlePreviewPause() {
		if (!activeSavedSegmentId || skipReportedSegmentId === activeSavedSegmentId) return;
		const duration = previewEndMs - previewStartMs;
		const listened = currentMs - previewStartMs;
		if (duration > 0 && listened >= 1000 && listened / duration < 0.5) {
			skipReportedSegmentId = activeSavedSegmentId;
			void recordStudioBehavior('early_skip', activeSavedSegmentId).catch(() => {});
		}
	}

	/** @param {import('$lib/types.js').SavedSegment} segment @param {string} label */
	async function renameSegment(segment, label) {
		if (!label.trim() || label.trim() === segment.label) return;
		try {
			const updated = await updateSavedSegment(segment.id, { label: label.trim() });
			savedSegments = savedSegments.map((row) => (row.id === segment.id ? updated : row));
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not rename segment.';
		}
	}

	/** @param {import('$lib/types.js').SavedSegment} segment */
	async function removeSaved(segment) {
		if (!confirm(`Delete “${segment.label}”? Existing mix snapshots will stay unchanged.`)) return;
		try {
			await deleteSavedSegment(segment.id);
			savedSegments = savedSegments.filter((row) => row.id !== segment.id);
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not delete segment.';
		}
	}

	/** @param {import('$lib/types.js').Mix} mix */
	function replaceMix(mix) {
		mixes = [mix, ...mixes.filter((row) => row.id !== mix.id)];
		activeMixId = mix.id;
	}

	async function createDraft() {
		if (!newMixTitle.trim()) return;
		try {
			replaceMix(await createStudioMix(newMixTitle.trim()));
			notice = 'Draft created. Every timeline change is saved immediately.';
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not create draft.';
		}
	}

	async function renameMix() {
		if (!activeMix || activeMix.status === 'published') return;
		try {
			replaceMix(
				await updateStudioMix(activeMix.id, activeMix.revision, { title: activeMix.title })
			);
			notice = 'Draft title saved.';
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Autosave conflict.';
		}
	}

	/** @param {import('$lib/types.js').SavedSegment} segment */
	async function addToMix(segment) {
		if (!activeMix) {
			error = 'Create or select a Studio draft first.';
			return;
		}
		try {
			replaceMix(await addSegmentToMix(activeMix.id, activeMix.revision, segment.id));
			notice = 'Segment snapshotted into the mix.';
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not add segment.';
		}
	}

	/** @param {number} index @param {number} direction */
	async function moveItem(index, direction) {
		if (!activeMix) return;
		const target = index + direction;
		if (target < 0 || target >= activeMix.segments.length) return;
		const ids = activeMix.segments.map((item) => Number(item.id));
		[ids[index], ids[target]] = [ids[target], ids[index]];
		try {
			replaceMix(await reorderStudioMix(activeMix.id, activeMix.revision, ids));
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not reorder mix.';
		}
	}

	/** @param {import('$lib/types.js').SessionSegment} item */
	async function removeItem(item) {
		if (!activeMix) return;
		try {
			replaceMix(await removeMixItem(activeMix.id, activeMix.revision, Number(item.id)));
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not remove item.';
		}
	}

	/** @param {import('$lib/types.js').SessionSegment} item @param {string} type @param {number} [durationMs] */
	async function changeTransition(item, type, durationMs = item.transitionDurationMs) {
		if (!activeMix) return;
		if (!['cut', 'crossfade', 'fade_in_out'].includes(type)) return;
		try {
			replaceMix(
				await updateStudioTransition(
					activeMix.id,
					Number(item.id),
					activeMix.revision,
					/** @type {'cut'|'crossfade'|'fade_in_out'} */ (type),
					Number(durationMs)
				)
			);
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not update transition.';
		}
	}

	/** @param {import('$lib/types.js').SessionSegment} item */
	async function previewTransition(item) {
		if (!activeMix) return;
		try {
			const url = await previewStudioTransition(activeMix.id, Number(item.id));
			await cueAudio(url, 0, 0);
		} catch (requestError) {
			error =
				requestError instanceof Error ? requestError.message : 'Could not preview transition.';
		}
	}

	async function renderMix() {
		if (!activeMix) return;
		busy = 'render';
		try {
			replaceMix(await renderStudioMix(activeMix.id));
			notice = 'Current draft revision rendered.';
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Render failed.';
		} finally {
			busy = '';
		}
	}

	async function publishMix() {
		if (!activeMix) return;
		try {
			replaceMix(await publishStudioMix(activeMix.id));
			notice = 'Immutable rendered version published.';
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not publish.';
		}
	}

	async function duplicateMix() {
		if (!activeMix) return;
		try {
			replaceMix(await duplicateStudioMix(activeMix.id));
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not duplicate mix.';
		}
	}

	async function createAutoMix() {
		try {
			replaceMix(
				await autoMixFromSaved({
					title: autoMixTitle.trim(),
					prompt: autoPrompt.trim(),
					mode: autoMode,
					limit: 5
				})
			);
			notice = 'Editable draft generated from your saved segments.';
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Auto-mix failed.';
		}
	}

	async function askAssistant() {
		const content = assistantInput.trim();
		if (!content || busy === 'assistant') return;
		assistantMessages = [
			...assistantMessages,
			/** @type {{role:'user',content:string}} */ ({ role: 'user', content })
		].slice(-12);
		assistantInput = '';
		busy = 'assistant';
		try {
			const result = await chatWithStudioAssistant(
				assistantMessages,
				activeMix?.id,
				activeSavedSegmentId
			);
			recommendation = result.recommendation;
			compareNextAi = true;
			assistantMessages = [
				...assistantMessages,
				/** @type {{role:'assistant',content:string}} */ ({
					role: 'assistant',
					content: result.recommendation.explanation
				})
			].slice(-12);
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Assistant unavailable.';
		} finally {
			busy = '';
		}
	}

	async function applyRecommendation() {
		if (!recommendation) return;
		try {
			if (
				recommendation.recommendation_type === 'segment_bounds' &&
				recommendation.candidate_id &&
				recommendation.proposed_start_ms != null &&
				recommendation.proposed_end_ms != null
			) {
				const updated = await updateSavedSegment(recommendation.candidate_id, {
					start_ms: recommendation.proposed_start_ms,
					end_ms: recommendation.proposed_end_ms
				});
				savedSegments = savedSegments.map((row) => (row.id === updated.id ? updated : row));
				await previewSaved(updated, false, false);
			} else if (
				recommendation.recommendation_type === 'mix_order' &&
				activeMix &&
				recommendation.proposed_order
			) {
				replaceMix(
					await reorderStudioMix(activeMix.id, activeMix.revision, recommendation.proposed_order)
				);
			} else if (
				recommendation.recommendation_type === 'transition' &&
				activeMix &&
				recommendation.transition_change
			) {
				const change = recommendation.transition_change;
				replaceMix(
					await updateStudioTransition(
						activeMix.id,
						change.item_id,
						activeMix.revision,
						change.transition_type,
						change.duration_ms
					)
				);
			}
			notice = 'Recommendation validated and applied.';
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Recommendation was rejected.';
		}
	}

	async function playAiRecommendation() {
		if (
			!recommendation?.candidate_id ||
			recommendation.proposed_start_ms == null ||
			recommendation.proposed_end_ms == null
		)
			return;
		const candidate = savedSegments.find((segment) => segment.id === recommendation?.candidate_id);
		if (!candidate) return;
		if (
			!selectedTrack ||
			selectedTrack.sourceType !== candidate.sourceType ||
			selectedTrack.sourceTrackId !== candidate.sourceTrackId
		) {
			await previewSaved(candidate, false, false);
		}
		await cueAudio(
			candidate.sourceAudioUrl,
			recommendation.proposed_start_ms,
			recommendation.proposed_end_ms
		);
	}

	async function compareRecommendation() {
		if (compareNextAi) {
			await playAiRecommendation();
			notice = 'Playing the AI suggestion. Press Compare again to hear your range.';
		} else if (selectedTrack) {
			await cueAudio(
				selectedTrack.audioUrl,
				Math.round(startSeconds * 1000),
				Math.round(endSeconds * 1000)
			);
			notice = 'Playing your current range.';
		}
		compareNextAi = !compareNextAi;
	}

	async function keepMine() {
		recommendation = null;
		compareNextAi = true;
		if (!selectedTrack) return;
		await cueAudio(
			selectedTrack.audioUrl,
			Math.round(startSeconds * 1000),
			Math.round(endSeconds * 1000),
			false
		);
	}

	/** @param {number|null|undefined} ms */
	function formatTime(ms) {
		const total = Math.max(0, Number(ms) || 0) / 1000;
		const minutes = Math.floor(total / 60);
		return `${minutes}:${(total % 60).toFixed(1).padStart(4, '0')}`;
	}
</script>

<svelte:head><title>CueMix Studio</title></svelte:head>

<main class="studio-page">
	<header class="studio-header">
		<div>
			<p class="eyebrow">Creator workspace</p>
			<h1>CueMix Studio</h1>
			<p>Choose exact moments, arrange transitions, render, and publish.</p>
		</div>
		<div class="save-state">
			<span class:live={activeMix?.renderStatus === 'ready'}></span>{activeMix
				? `Revision ${activeMix.revision} · ${activeMix.renderStatus.replaceAll('_', ' ')}`
				: 'No draft selected'}
		</div>
	</header>

	{#if error}<div class="banner error" role="alert">
			{error}<button onclick={() => (error = '')}>Dismiss</button>
		</div>{/if}
	{#if notice}<div class="banner success" aria-live="polite">
			{notice}<button onclick={() => (notice = '')}>Dismiss</button>
		</div>{/if}

	<section class="studio-grid">
		<aside class="panel music-panel">
			<div class="panel-title">
				<div>
					<p class="eyebrow">Music</p>
					<h2>Find a track</h2>
				</div>
			</div>
			<form
				class="search"
				onsubmit={(event) => {
					event.preventDefault();
					void runSearch();
				}}
			>
				<input bind:value={searchQuery} placeholder="Track or artist" aria-label="Track search" />
				<select bind:value={sourceFilter} aria-label="Music source"
					><option value="all">All</option><option value="catalog">Uploads</option><option
						value="audius">Audius</option
					></select
				>
				<button type="submit">{busy === 'search' ? '…' : 'Search'}</button>
			</form>
			<div class="track-list">
				{#each tracks as track (track.sourceType + track.sourceTrackId)}
					<button
						class:selected={selectedTrack?.sourceTrackId === track.sourceTrackId &&
							selectedTrack?.sourceType === track.sourceType}
						class="track-row"
						onclick={() => chooseTrack(track)}
					>
						<span class="cover">{track.title.slice(0, 2).toUpperCase()}</span><span
							><strong>{track.title}</strong><small
								>{track.artist} · {track.sourceType} · {formatTime(track.durationMs)}</small
							></span
						>
					</button>
				{:else}<p class="empty">No matching tracks. Search Audius or upload music first.</p>{/each}
			</div>

			<div class="library-head">
				<h3>My segments</h3>
				<input bind:value={segmentFilter} placeholder="Filter" aria-label="Filter saved segments" />
			</div>
			<div class="segment-list">
				{#each filteredSegments as segment (segment.id)}
					<article class="saved-row">
						<div>
							<input
								class="label-input"
								value={segment.label}
								onchange={(event) => renameSegment(segment, event.currentTarget.value)}
							/><small>{segment.title} · {segment.artist}</small><small
								>{formatTime(segment.startMs)} → {formatTime(segment.endMs)}</small
							>
						</div>
						<div class="row-actions">
							<button onclick={() => previewSaved(segment, true)}>Play</button><button
								onclick={() => addToMix(segment)}>Add</button
							><button class="danger" onclick={() => removeSaved(segment)}>×</button>
						</div>
					</article>
				{:else}<p class="empty">Save your first exact moment.</p>{/each}
			</div>
		</aside>

		<section class="panel editor-panel">
			<div class="panel-title">
				<div>
					<p class="eyebrow">Track / segment editor</p>
					<h2>{selectedTrack?.title || 'Select a track'}</h2>
				</div>
				{#if selectedTrack}<span class="source-pill">{selectedTrack.sourceType}</span>{/if}
			</div>
			<audio
				bind:this={audioElement}
				src={previewUrl}
				controls
				ontimeupdate={handleTimeUpdate}
				onseeked={handleTimeUpdate}
				onpause={handlePreviewPause}
			></audio>
			{#if selectedTrack && editingSelectedTrack}
				<WaveformSegmentEditor
					media={audioElement}
					audioUrl={selectedTrack.audioUrl}
					durationMs={selectedTrack.durationMs}
					startMs={Math.round(startSeconds * 1000)}
					endMs={Math.round(endSeconds * 1000)}
					currentTimeMs={currentMs}
					minDurationMs={selectedTrack.minSegmentMs}
					maxDurationMs={selectedTrack.maxSegmentMs}
					analysisMarkers={waveformMarkers}
					onStartChange={handleWaveformStart}
					onEndChange={handleWaveformEnd}
					onSeek={seekFromWaveform}
				/>
			{:else if selectedTrack}
				<p class="waveform-away">The waveform returns when you play or edit the selected track.</p>
			{/if}
			<div class="time-readout">
				<strong data-testid="studio-current-time">{formatTime(currentMs)}</strong><span
					>/ {formatTime(selectedTrack?.durationMs || previewEndMs)}</span
				>
			</div>
			<div class="bounds-grid">
				<label
					>Start (seconds)<input
						type="number"
						min="0"
						step="0.001"
						value={startSeconds}
						data-testid="segment-start-input"
						oninput={(event) =>
							setSelectionMs(
								Math.round(Number(event.currentTarget.value) * 1000),
								Math.round(endSeconds * 1000),
								'start'
							)}
					/></label
				><button onclick={setStartHere}>Set current as start</button>
				<label
					>End (seconds)<input
						type="number"
						min="0"
						step="0.001"
						value={endSeconds}
						data-testid="segment-end-input"
						oninput={(event) =>
							setSelectionMs(
								Math.round(startSeconds * 1000),
								Math.round(Number(event.currentTarget.value) * 1000),
								'end'
							)}
					/></label
				><button onclick={setEndHere}>Set current as end</button>
			</div>
			<div class="duration-card">
				<span>Exact duration</span><strong>{(selectionDurationMs / 1000).toFixed(1)} sec</strong>
			</div>
			<label>Segment label<input bind:value={segmentLabel} maxlength="120" /></label>
			<div class="editor-actions">
				<button
					class="primary"
					disabled={!selectedTrack}
					onclick={() =>
						cueAudio(
							selectedTrack?.audioUrl || '',
							Math.round(startSeconds * 1000),
							Math.round(endSeconds * 1000)
						)}>Play segment</button
				><label class="loop"><input type="checkbox" bind:checked={loopPreview} /> Loop</label
				><button
					class="accent"
					disabled={!selectedTrack || busy === 'save-segment'}
					onclick={saveSelection}>{busy === 'save-segment' ? 'Validating…' : 'Save segment'}</button
				>
			</div>
			<p class="guard-note">
				The backend rechecks ownership, duration, exact bounds, decodability, and silence before
				saving.
			</p>
		</section>

		<aside class:collapsed={!assistantOpen} class="panel assistant-panel">
			<div class="panel-title">
				<div>
					<p class="eyebrow">Local LLM</p>
					<h2>AI Mix Assistant</h2>
				</div>
				<button class="ghost" onclick={() => (assistantOpen = !assistantOpen)}
					>{assistantOpen ? 'Collapse' : 'Open'}</button
				>
			</div>
			{#if assistantOpen}
				<div class="chat-log">
					{#each assistantMessages as message, index (index)}<p
							class:user={message.role === 'user'}
						>
							<b>{message.role === 'user' ? 'You' : 'Assistant'}</b>{message.content}
						</p>{:else}<p class="empty">
							Ask for stronger sections, smoother transitions, or a new energy arc. The assistant
							can suggest, never mutate.
						</p>{/each}
				</div>
				<form
					class="assistant-form"
					onsubmit={(event) => {
						event.preventDefault();
						void askAssistant();
					}}
				>
					<textarea
						bind:value={assistantInput}
						maxlength="2000"
						placeholder="Keep this segment, but make the next transition smoother…"
					></textarea><button
						class="primary"
						disabled={!assistantInput.trim() || busy === 'assistant'}
						>{busy === 'assistant' ? 'Thinking…' : 'Ask assistant'}</button
					>
				</form>
				{#if recommendation}<article class="recommendation">
						<span>{recommendation.recommendation_type.replaceAll('_', ' ')}</span><strong
							>{Math.round(recommendation.confidence * 100)}% grounded confidence</strong
						>
						<p>{recommendation.explanation}</p>
						{#if recommendation.reason_tags?.length}<small
								>{recommendation.reason_tags.join(' · ')}</small
							>{/if}
						<div class="row-actions">
							{#if recommendation.recommendation_type === 'segment_bounds'}
								<button onclick={playAiRecommendation}>Play AI</button><button
									onclick={compareRecommendation}>Compare</button
								>
							{/if}
							<button
								class="accent"
								disabled={recommendation.recommendation_type === 'unavailable' ||
									recommendation.recommendation_type === 'explanation'}
								onclick={applyRecommendation}>Apply after validation</button
							><button onclick={keepMine}>Keep Mine</button>
						</div>
					</article>{/if}
			{/if}
		</aside>
	</section>

	<section class="panel timeline-panel">
		<div class="timeline-head">
			<div>
				<p class="eyebrow">Mix timeline</p>
				<h2>{activeMix?.title || 'Create a Studio draft'}</h2>
			</div>
			<div class="draft-controls">
				<select bind:value={activeMixId} aria-label="Active Studio mix"
					><option value={0}>Select draft</option>{#each mixes as mix (mix.id)}<option
							value={mix.id}>{mix.title} · r{mix.revision}</option
						>{/each}</select
				><input bind:value={newMixTitle} aria-label="New mix title" /><button onclick={createDraft}
					>New draft</button
				>
			</div>
		</div>

		{#if activeMix}
			<div class="mix-meta">
				<input
					value={activeMix.title}
					oninput={(event) => {
						activeMix.title = event.currentTarget.value;
					}}
					onblur={renameMix}
					disabled={activeMix.status === 'published'}
				/><span
					>{activeMix.segments.reduce(
						(sum, item) => sum + Math.max(0, (item.sourceEndMs || 0) - (item.sourceStartMs || 0)),
						0
					) / 1000}s total</span
				><span>{activeMix.status}</span>
			</div>
			<div class="timeline">
				{#each activeMix.segments as item, index (item.id)}
					<article class="timeline-item">
						<header>
							<span>{index + 1}</span>
							<div>
								<strong>{item.title}</strong><small
									>{item.artist} · {formatTime(
										(item.sourceEndMs || 0) - (item.sourceStartMs || 0)
									)}</small
								>
							</div>
						</header>
						<div class="chips">
							{#if item.bpm}<span>{item.bpm} BPM</span
								>{/if}{#if item.camelot || item.musicalKey}<span
									>{item.camelot || item.musicalKey}</span
								>{/if}
						</div>
						<div class="item-actions">
							<button
								disabled={index === 0 || activeMix.status === 'published'}
								onclick={() => moveItem(index, -1)}>←</button
							><button
								disabled={index === activeMix.segments.length - 1 ||
									activeMix.status === 'published'}
								onclick={() => moveItem(index, 1)}>→</button
							><button
								onclick={() =>
									cueAudio(item.sourceAudioUrl, item.sourceStartMs ?? 0, item.sourceEndMs ?? 0)}
								>Play</button
							><button
								class="danger"
								disabled={activeMix.status === 'published'}
								onclick={() => removeItem(item)}>Remove</button
							>
						</div>
					</article>
					{#if index < activeMix.segments.length - 1}<div class="transition-card">
							<strong>Compatibility {item.compatibilityScore ?? '—'}/100</strong><small
								>{item.compatibilityFactors
									? `Tempo ${item.compatibilityFactors.tempo} · Key ${item.compatibilityFactors.key} · Energy ${item.compatibilityFactors.energy} · Phrase ${item.compatibilityFactors.phrase}`
									: 'Metadata unavailable'}</small
							>
							<div>
								<select
									value={item.transitionType}
									disabled={activeMix.status === 'published'}
									onchange={(event) => changeTransition(item, event.currentTarget.value)}
									><option value="cut">Cut</option><option value="crossfade">Crossfade</option
									><option value="fade_in_out">Fade in/out</option></select
								><input
									type="number"
									min="0"
									max="8000"
									step="100"
									value={item.transitionDurationMs}
									disabled={activeMix.status === 'published' || item.transitionType === 'cut'}
									onchange={(event) =>
										changeTransition(item, item.transitionType, Number(event.currentTarget.value))}
								/><button onclick={() => previewTransition(item)}>Preview</button>
							</div>
						</div>{/if}
				{:else}<p class="empty wide">
						Add saved segments from the left panel. Bounds are snapshotted, so later library edits
						cannot alter this draft.
					</p>{/each}
			</div>
			<div class="render-actions">
				{#if activeMix.status === 'published'}<button onclick={duplicateMix}
						>Duplicate into editable draft</button
					>{:else}<button
						class="primary"
						disabled={!activeMix.segments.length || busy === 'render'}
						onclick={renderMix}
						>{busy === 'render' ? 'Rendering…' : 'Render current revision'}</button
					><button
						class="accent"
						disabled={activeMix.renderStatus !== 'ready' ||
							activeMix.renderedRevision !== activeMix.revision}
						onclick={publishMix}>Publish immutable render</button
					>{/if}{#if activeMix.renderedAudioUrl}<button
						onclick={() => cueAudio(activeMix.renderedAudioUrl || '', 0, 0)}
						>Play full render</button
					>{/if}
			</div>
		{/if}

		<div class="auto-mix">
			<div>
				<p class="eyebrow">Auto-mix source</p>
				<h3>My saved segments</h3>
			</div>
			<input bind:value={autoMixTitle} placeholder="Draft title" /><input
				bind:value={autoPrompt}
				placeholder="Custom intent"
			/><AutoMixModeSelector
				value={autoMode}
				compact
				onChange={(mode) => (autoMode = mode)}
				onDefaultPrompt={(prompt) => (autoPrompt = prompt)}
			/><button class="accent" disabled={!savedSegments.length} onclick={createAutoMix}
				>Generate editable draft</button
			>
		</div>
	</section>
</main>

<style>
	.studio-page {
		display: grid;
		gap: 18px;
		padding: 26px 0 80px;
		color: #dceaff;
	}
	.studio-header,
	.panel-title,
	.timeline-head,
	.library-head,
	.mix-meta,
	.render-actions,
	.editor-actions,
	.row-actions {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
	}
	.studio-header h1 {
		margin: 2px 0;
		font-size: clamp(34px, 5vw, 64px);
		letter-spacing: -0.055em;
	}
	.studio-header p,
	.panel h2,
	.panel h3 {
		margin: 0;
	}
	.eyebrow {
		color: #5fe0c0 !important;
		font-size: 10px;
		font-weight: 900;
		letter-spacing: 0.16em;
		text-transform: uppercase;
	}
	.save-state {
		padding: 10px 14px;
		border: 1px solid #20324d;
		border-radius: 999px;
		color: #8499b5;
		font-size: 12px;
	}
	.save-state span {
		display: inline-block;
		width: 7px;
		height: 7px;
		margin-right: 7px;
		border-radius: 50%;
		background: #697990;
	}
	.save-state span.live {
		background: #4fe0ad;
	}
	.banner {
		display: flex;
		justify-content: space-between;
		padding: 12px 16px;
		border-radius: 14px;
	}
	.banner.error {
		border: 1px solid #74394a;
		background: #2b1420;
		color: #ffadbd;
	}
	.banner.success {
		border: 1px solid #24594d;
		background: #102a26;
		color: #82e9c9;
	}
	.banner button,
	.ghost {
		border: 0;
		background: transparent;
		color: inherit;
	}
	.studio-grid {
		display: grid;
		grid-template-columns: minmax(250px, 0.8fr) minmax(340px, 1.25fr) minmax(280px, 0.85fr);
		gap: 14px;
	}
	.panel {
		min-width: 0;
		border: 1px solid #1d304a;
		border-radius: 22px;
		background: linear-gradient(145deg, #0b1729, #091320);
		box-shadow: 0 20px 50px rgba(0, 0, 0, 0.18);
		padding: 18px;
	}
	.panel-title {
		margin-bottom: 14px;
	}
	.panel-title h2 {
		font-size: 20px;
	}
	.search {
		display: grid;
		grid-template-columns: 1fr auto auto;
		gap: 7px;
	}
	.search input,
	.search select,
	.search button,
	input,
	select,
	textarea,
	button {
		font: inherit;
	}
	.search input,
	.search select,
	.bounds-grid input,
	.panel > label input,
	.library-head input,
	.draft-controls input,
	.draft-controls select,
	.mix-meta input,
	.auto-mix input,
	.transition-card input,
	.transition-card select,
	textarea {
		border: 1px solid #263b58;
		border-radius: 10px;
		background: #07101d;
		color: #dceaff;
		padding: 9px;
	}
	.search button,
	.row-actions button,
	.item-actions button,
	.render-actions button,
	.draft-controls button,
	.bounds-grid button,
	.editor-actions button,
	.assistant-form button,
	.auto-mix button,
	.transition-card button {
		border: 1px solid #29415f;
		border-radius: 10px;
		background: #101f34;
		color: #bbcee8;
		padding: 8px 10px;
		cursor: pointer;
	}
	.primary {
		background: #315fda !important;
		color: white !important;
	}
	.accent {
		border-color: #2c8272 !important;
		background: #173f39 !important;
		color: #78ebcb !important;
	}
	.danger {
		color: #ff9aac !important;
	}
	.track-list,
	.segment-list,
	.chat-log {
		display: grid;
		gap: 8px;
		max-height: 330px;
		overflow: auto;
		margin-top: 12px;
	}
	.track-row {
		display: flex;
		align-items: center;
		gap: 10px;
		width: 100%;
		padding: 10px;
		border: 1px solid transparent;
		border-radius: 13px;
		background: #0c1a2d;
		color: inherit;
		text-align: left;
	}
	.track-row.selected {
		border-color: #5a79f1;
		background: #132442;
	}
	.track-row span:last-child {
		display: grid;
		min-width: 0;
	}
	.track-row strong,
	.track-row small,
	.saved-row small {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.track-row small,
	.saved-row small,
	.transition-card small,
	.guard-note {
		color: #7188a6;
		font-size: 11px;
	}
	.cover {
		display: grid;
		width: 38px;
		height: 38px;
		flex: none;
		place-items: center;
		border-radius: 11px;
		background: linear-gradient(135deg, #325cb8, #6955bd);
		font-size: 10px;
		font-weight: 900;
	}
	.library-head {
		margin-top: 20px;
	}
	.library-head input {
		width: 95px;
	}
	.saved-row {
		display: grid;
		gap: 8px;
		padding: 10px;
		border: 1px solid #1b2c43;
		border-radius: 13px;
	}
	.saved-row > div:first-child {
		display: grid;
		gap: 2px;
	}
	.label-input {
		border: 0;
		background: transparent;
		color: #dceaff;
		font-weight: 800;
	}
	.row-actions {
		justify-content: flex-start;
	}
	.empty {
		color: #71839c;
		font-size: 12px;
	}
	.source-pill,
	.chips span,
	.recommendation > span {
		padding: 5px 8px;
		border-radius: 999px;
		background: #152743;
		color: #8eb4ec;
		font-size: 10px;
		text-transform: uppercase;
	}
	.editor-panel audio {
		width: 100%;
		margin: 12px 0;
	}
	.time-readout {
		display: flex;
		align-items: baseline;
		gap: 6px;
		margin: 14px 0;
	}
	.time-readout strong {
		font-size: 32px;
	}
	.time-readout span {
		color: #6f829d;
	}
	.bounds-grid {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: 10px;
		align-items: end;
	}
	.bounds-grid label,
	.editor-panel > label {
		display: grid;
		gap: 6px;
		color: #8195b0;
		font-size: 11px;
	}
	.duration-card {
		display: flex;
		justify-content: space-between;
		margin: 14px 0;
		padding: 13px;
		border: 1px solid #243a58;
		border-radius: 13px;
		background: #0d1b2e;
	}
	.duration-card span {
		color: #7790ae;
	}
	.loop {
		display: flex !important;
		align-items: center;
		gap: 6px;
	}
	.guard-note {
		line-height: 1.5;
	}
	.waveform-away {
		margin: 8px 0 14px;
		padding: 10px;
		border: 1px dashed #29415f;
		border-radius: 12px;
		color: #7f94b0;
		font-size: 11px;
		text-align: center;
	}
	.assistant-panel.collapsed {
		align-self: start;
	}
	.chat-log p {
		display: grid;
		gap: 4px;
		margin: 0;
		padding: 10px;
		border-radius: 12px;
		background: #0d1b2d;
		color: #9fb2cc;
		font-size: 12px;
	}
	.chat-log p.user {
		background: #162744;
		color: #d8e6fb;
	}
	.chat-log b {
		font-size: 9px;
		text-transform: uppercase;
		color: #67d6bd;
	}
	.assistant-form {
		display: grid;
		gap: 8px;
		margin-top: 10px;
	}
	.assistant-form textarea {
		min-height: 90px;
		resize: vertical;
	}
	.recommendation {
		display: grid;
		gap: 8px;
		margin-top: 12px;
		padding: 13px;
		border: 1px solid #345372;
		border-radius: 14px;
		background: #102238;
	}
	.recommendation p {
		margin: 0;
		color: #b8cbe4;
		font-size: 12px;
	}
	.timeline-panel {
		display: grid;
		gap: 16px;
	}
	.draft-controls {
		display: flex;
		gap: 7px;
	}
	.timeline {
		display: flex;
		align-items: stretch;
		gap: 10px;
		overflow: auto;
		padding-bottom: 8px;
	}
	.timeline-item {
		display: grid;
		min-width: 220px;
		gap: 10px;
		padding: 13px;
		border: 1px solid #243852;
		border-radius: 15px;
		background: #0c192a;
	}
	.timeline-item header {
		display: flex;
		gap: 9px;
	}
	.timeline-item header > span {
		display: grid;
		width: 26px;
		height: 26px;
		place-items: center;
		border-radius: 8px;
		background: #1b3152;
		color: #7fdac2;
		font-weight: 900;
	}
	.timeline-item header div {
		display: grid;
	}
	.timeline-item small {
		color: #748ba8;
	}
	.chips {
		display: flex;
		gap: 6px;
	}
	.item-actions {
		display: flex;
		gap: 5px;
	}
	.item-actions button {
		padding: 6px 8px;
	}
	.transition-card {
		display: grid;
		min-width: 235px;
		place-content: center;
		gap: 7px;
		padding: 13px;
		border: 1px dashed #335270;
		border-radius: 15px;
		color: #b5cae4;
	}
	.transition-card > div {
		display: flex;
		gap: 5px;
	}
	.transition-card input {
		width: 70px;
	}
	.wide {
		min-width: 100%;
		text-align: center;
	}
	.mix-meta input {
		flex: 1;
		font-size: 18px;
		font-weight: 800;
	}
	.mix-meta span {
		color: #7c91ad;
		font-size: 11px;
	}
	.auto-mix {
		display: grid;
		grid-template-columns: auto minmax(150px, 0.6fr) minmax(220px, 1fr) minmax(300px, 1.2fr) auto;
		align-items: center;
		gap: 9px;
		padding-top: 14px;
		border-top: 1px solid #1b2d45;
	}
	.auto-mix h3 {
		margin: 0;
	}
	button:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}
	@media (max-width: 1100px) {
		.studio-grid {
			grid-template-columns: 1fr 1fr;
		}
		.assistant-panel {
			grid-column: 1/-1;
		}
		.auto-mix {
			grid-template-columns: 1fr 1fr;
		}
		.auto-mix > div {
			grid-column: 1/-1;
		}
	}
	@media (max-width: 720px) {
		.studio-grid {
			grid-template-columns: 1fr;
		}
		.assistant-panel {
			grid-column: auto;
		}
		.studio-header,
		.timeline-head,
		.draft-controls,
		.mix-meta,
		.render-actions,
		.editor-actions {
			align-items: stretch;
			flex-direction: column;
		}
		.search {
			grid-template-columns: 1fr;
		}
		.bounds-grid {
			grid-template-columns: 1fr;
		}
		.auto-mix {
			grid-template-columns: 1fr;
		}
		.timeline {
			scroll-snap-type: x mandatory;
		}
		.timeline-item,
		.transition-card {
			scroll-snap-align: start;
			min-width: 84vw;
		}
	}
</style>
