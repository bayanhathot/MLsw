<script>
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { tick } from 'svelte';

	import AutoMixModeSelector from '$lib/components/AutoMixModeSelector.svelte';
	import WaveformSegmentEditor from '$lib/components/WaveformSegmentEditor.svelte';
	import {
		addSegmentToMix,
		applyStudioAssistantPlan,
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
	let activeMixHasProviderAudio = $derived(
		Boolean(activeMix?.segments.some((segment) => segment.source !== 'catalog'))
	);
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
		const bound = recommendation?.segment_bound_change;
		const recommendationCandidateId = bound?.candidate_id;
		const candidate = recommendationCandidateId
			? savedSegments.find((segment) => segment.id === recommendationCandidateId)
			: null;
		if (
			candidate &&
			candidate.sourceType === selectedTrack.sourceType &&
			candidate.sourceTrackId === selectedTrack.sourceTrackId &&
			bound?.proposed_start_ms != null &&
			bound?.proposed_end_ms != null
		) {
			markers.push({
				kind: 'ai',
				startMs: bound.proposed_start_ms,
				endMs: bound.proposed_end_ms,
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
		const remainsPrivate = activeMixHasProviderAudio;
		busy = 'render';
		error = '';
		try {
			replaceMix(await renderStudioMix(activeMix.id));
			notice = remainsPrivate
				? 'Audius mix rendered and saved privately. You can play the full render below.'
				: 'Current draft revision rendered.';
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Render failed.';
		} finally {
			busy = '';
		}
	}

	async function publishMix() {
		if (!activeMix) return;
		if (activeMixHasProviderAudio) {
			error = '';
			notice = 'Audius mixes stay private because provider audio cannot be republished publicly.';
			return;
		}
		busy = 'publish';
		error = '';
		try {
			replaceMix(await publishStudioMix(activeMix.id));
			notice = 'Immutable rendered version published.';
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not publish.';
		} finally {
			busy = '';
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
		if (!recommendation || recommendation.recommendation_type !== 'plan') return;
		busy = 'assistant-apply';
		error = '';
		try {
			const applied = await applyStudioAssistantPlan(recommendation, activeMix?.id);
			if (applied.mix) replaceMix(applied.mix);
			if (applied.savedSegment) {
				const updated = applied.savedSegment;
				savedSegments = savedSegments.map((row) => (row.id === updated.id ? updated : row));
				await previewSaved(updated, false, false);
			}
			recommendation = null;
			notice = 'The complete assistant plan was validated and applied atomically.';
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Assistant plan was rejected.';
		} finally {
			busy = '';
		}
	}

	async function playAiRecommendation() {
		const bound = recommendation?.segment_bound_change;
		if (!bound?.candidate_id || bound.proposed_start_ms == null || bound.proposed_end_ms == null)
			return;
		const candidate = savedSegments.find((segment) => segment.id === bound.candidate_id);
		if (!candidate) return;
		if (
			!selectedTrack ||
			selectedTrack.sourceType !== candidate.sourceType ||
			selectedTrack.sourceTrackId !== candidate.sourceTrackId
		) {
			await previewSaved(candidate, false, false);
		}
		await cueAudio(candidate.sourceAudioUrl, bound.proposed_start_ms, bound.proposed_end_ms);
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

	/** @param {number} itemId */
	function assistantItemLabel(itemId) {
		const item = activeMix?.segments.find((segment) => segment.id === itemId);
		return item ? `${item.title} — ${item.artist}` : `Mix item ${itemId}`;
	}
</script>

<svelte:head>
	<title>CueMix Studio</title>
	<link rel="preconnect" href="https://fonts.googleapis.com" />
	<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin="anonymous" />
	<link
		href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600;700;800;900&display=swap"
		rel="stylesheet"
	/>
</svelte:head>

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
				{#if savedSegments.length}
					<input
						bind:value={segmentFilter}
						placeholder="Filter"
						aria-label="Filter saved segments"
					/>
				{/if}
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
					<p class="eyebrow">Local LLM · always thinking</p>
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
							Give the analyst several constraints at once: duration, locked tracks, energy arc, BPM
							jumps, and transition style. It remembers this conversation and waits for your
							confirmation before applying a plan.
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
						placeholder="Keep the first track, stay under 2:30, increase energy, and minimize BPM jumps…"
					></textarea><button
						class="primary"
						disabled={!assistantInput.trim() || busy === 'assistant'}
						>{busy === 'assistant' ? 'Reasoning…' : 'Ask assistant'}</button
					>
				</form>
				{#if recommendation}<article class="recommendation">
						<span>{recommendation.recommendation_type.replaceAll('_', ' ')}</span><strong
							>{Math.round(recommendation.confidence * 100)}% grounded confidence</strong
						>
						<p>{recommendation.explanation}</p>
						{#if recommendation.remembered_constraints?.length}
							<section class="assistant-detail">
								<b>Remembered constraints</b>
								<ul>
									{#each recommendation.remembered_constraints as constraint, constraintIndex (`${constraint}-${constraintIndex}`)}<li
										>
											{constraint}
										</li>{/each}
								</ul>
							</section>
						{/if}
						{#if recommendation.calculations}
							<div class="assistant-math">
								<span
									>Current<strong
										>{formatTime(recommendation.calculations.current_duration_ms)}</strong
									></span
								>
								<span
									>Proposed<strong
										>{formatTime(recommendation.calculations.proposed_duration_ms)}</strong
									></span
								>
								<span
									>Overlap<strong
										>{formatTime(recommendation.calculations.transition_overlap_ms)}</strong
									></span
								>
								<span
									>BPM jump<strong
										>{recommendation.calculations.average_bpm_jump == null
											? 'No data'
											: recommendation.calculations.average_bpm_jump.toFixed(1)}</strong
									></span
								>
							</div>
						{/if}
						{#if recommendation.proposed_order?.length}
							<section class="assistant-detail">
								<b>Proposed order</b>
								<ol>
									{#each recommendation.proposed_order as itemId (itemId)}<li>
											{assistantItemLabel(itemId)}
										</li>{/each}
								</ol>
							</section>
						{/if}
						{#if recommendation.transition_changes?.length}
							<section class="assistant-detail">
								<b>Transition changes</b>
								<ul>
									{#each recommendation.transition_changes as change (change.item_id)}<li>
											{assistantItemLabel(change.item_id)}: {change.transition_type.replaceAll(
												'_',
												' '
											)}
											· {(change.duration_ms / 1000).toFixed(1)}s
										</li>{/each}
								</ul>
							</section>
						{/if}
						{#if recommendation.segment_bound_change}
							<p class="assistant-bound">
								Saved segment range: {formatTime(
									recommendation.segment_bound_change.proposed_start_ms
								)}–{formatTime(recommendation.segment_bound_change.proposed_end_ms)}
							</p>
						{/if}
						{#if recommendation.warnings?.length}
							<section class="assistant-detail warning-list">
								<b>Warnings</b>
								<ul>
									{#each recommendation.warnings as warning, warningIndex (`${warning}-${warningIndex}`)}<li
										>
											{warning}
										</li>{/each}
								</ul>
							</section>
						{/if}
						{#if recommendation.reason_tags?.length}<small
								>{recommendation.reason_tags.join(' · ')}</small
							>{/if}
						<div class="row-actions">
							{#if recommendation.segment_bound_change}
								<button onclick={playAiRecommendation}>Play AI</button><button
									onclick={compareRecommendation}>Compare</button
								>
							{/if}
							{#if recommendation.recommendation_type === 'plan'}<button
									class="accent"
									disabled={busy === 'assistant-apply'}
									onclick={applyRecommendation}
									>{busy === 'assistant-apply' ? 'Validating…' : 'Confirm and apply plan'}</button
								>{/if}<button onclick={keepMine}>Keep Mine</button>
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
							<div class="meter-row">
								<strong>Compatibility {item.compatibilityScore ?? '—'}/100</strong>
								<div
									class="meter"
									aria-hidden="true"
									style={`--fill:${Math.max(0, Math.min(100, item.compatibilityScore ?? 0))}%`}
								>
									<span></span>
								</div>
							</div>
							<small
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
					>
					{#if activeMixHasProviderAudio}
						<p class="publish-note" role="status">
							Audius audio can be rendered and played here, but the mix stays private and is not
							republished as a public CueMix asset.
						</p>
					{:else}
						<button
							class="accent"
							disabled={activeMix.renderStatus !== 'ready' ||
								activeMix.renderedRevision !== activeMix.revision ||
								busy === 'publish'}
							onclick={publishMix}
							>{busy === 'publish' ? 'Publishing…' : 'Publish immutable render'}</button
						>
					{/if}{/if}{#if activeMix.renderedAudioUrl}<button
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
			/><button class="accent" disabled={!savedSegments.length} onclick={createAutoMix}
				>Generate editable draft</button
			>
		</div>
	</section>
</main>

<style>
	.studio-page {
		--rack: #0b0e13;
		--panel: #161b22;
		--panel-raised: #1d232c;
		--well: #0a0c10;
		--seam: rgba(255, 255, 255, 0.07);
		--text: #eef2f6;
		--text-dim: #93a0b0;
		--text-faint: #5c6673;
		--amber: #ff9548;
		--amber-dim: rgba(255, 149, 72, 0.15);
		--cyan: #3fe6bb;
		--cyan-dim: rgba(63, 230, 187, 0.14);
		--key-blue: #7c9eff;
		--danger: #ff5c72;
		--danger-dim: rgba(255, 92, 114, 0.14);
		--font-display: 'Space Grotesk', 'Outfit', ui-sans-serif, system-ui, sans-serif;
		--font-ui: 'Inter', ui-sans-serif, system-ui, sans-serif;
		--font-mono: 'JetBrains Mono', ui-monospace, 'SFMono-Regular', Menlo, monospace;

		display: grid;
		gap: 18px;
		padding: 26px 0 80px;
		color: var(--text);
		background: var(--rack);
		font-family: var(--font-ui);
	}
	.studio-page :is(input, select, textarea, button) {
		font-family: var(--font-ui);
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
	.studio-header {
		align-items: flex-end;
	}
	.studio-header h1 {
		position: relative;
		margin: 6px 0 0;
		padding-bottom: 14px;
		font-family: var(--font-display);
		font-size: clamp(30px, 4.4vw, 52px);
		font-weight: 600;
		letter-spacing: -0.02em;
	}
	.studio-header h1::after {
		content: '';
		position: absolute;
		left: 1px;
		bottom: 0;
		width: 46px;
		height: 3px;
		border-radius: 2px;
		background: var(--amber);
		box-shadow: 0 0 12px var(--amber-dim);
	}
	.studio-header p,
	.panel h2,
	.panel h3 {
		margin: 0;
	}
	.eyebrow {
		color: var(--text-faint) !important;
		font-family: var(--font-mono);
		font-size: 10px;
		font-weight: 600;
		letter-spacing: 0.18em;
		text-transform: uppercase;
	}
	.save-state {
		padding: 9px 14px;
		border: 1px solid var(--seam);
		border-radius: 999px;
		background: var(--well);
		color: var(--text-dim);
		font-family: var(--font-mono);
		font-size: 11px;
		letter-spacing: 0.02em;
		font-variant-numeric: tabular-nums;
	}
	.save-state span {
		display: inline-block;
		width: 7px;
		height: 7px;
		margin-right: 8px;
		border-radius: 50%;
		background: var(--text-faint);
	}
	.save-state span.live {
		background: var(--amber);
		box-shadow: 0 0 8px 1px var(--amber-dim);
	}
	.banner {
		display: flex;
		justify-content: space-between;
		padding: 12px 16px;
		border-radius: 12px;
	}
	.banner.error {
		border: 1px solid rgba(255, 92, 114, 0.4);
		background: var(--danger-dim);
		color: #ffb2c0;
	}
	.banner.success {
		border: 1px solid rgba(63, 230, 187, 0.38);
		background: var(--cyan-dim);
		color: #a7f2dc;
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
		position: relative;
		min-width: 0;
		border: 1px solid var(--seam);
		border-radius: 12px;
		background: var(--panel);
		box-shadow:
			inset 0 1px 0 rgba(255, 255, 255, 0.04),
			0 16px 40px rgba(0, 0, 0, 0.4);
		padding: 18px;
	}
	.panel-title {
		margin-bottom: 16px;
		padding-bottom: 12px;
		border-bottom: 1px solid var(--seam);
	}
	.panel-title h2 {
		font-family: var(--font-display);
		font-size: 19px;
		font-weight: 600;
		letter-spacing: -0.01em;
	}
	.search {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: 7px;
	}
	.search input {
		grid-column: 1 / -1;
		min-width: 0;
	}
	.search select {
		min-width: 0;
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
		border: 1px solid var(--seam);
		border-radius: 8px;
		background: var(--well);
		color: var(--text);
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
		border: 1px solid var(--seam);
		border-radius: 8px;
		background: var(--panel-raised);
		color: var(--text-dim);
		padding: 8px 10px;
		cursor: pointer;
		transition: border-color 0.15s ease;
	}
	.search button:hover,
	.row-actions button:hover,
	.item-actions button:hover,
	.render-actions button:hover,
	.draft-controls button:hover,
	.bounds-grid button:hover,
	.editor-actions button:hover,
	.assistant-form button:hover,
	.auto-mix button:hover,
	.transition-card button:hover {
		border-color: var(--text-faint);
	}
	.publish-note {
		flex: 1 1 300px;
		margin: 0;
		color: var(--text-dim);
		font-size: 12px;
		line-height: 1.45;
	}
	.primary {
		border-color: var(--text) !important;
		background: var(--text) !important;
		color: var(--rack) !important;
		font-weight: 700;
	}
	.accent {
		border-color: rgba(63, 230, 187, 0.5) !important;
		background: var(--cyan-dim) !important;
		color: var(--cyan) !important;
		font-weight: 700;
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
		border-radius: 10px;
		background: var(--well);
		color: inherit;
		text-align: left;
	}
	.track-row.selected {
		border-color: rgba(63, 230, 187, 0.5);
		background: var(--cyan-dim);
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
		color: var(--text-faint);
		font-size: 11px;
	}
	.cover {
		display: grid;
		width: 38px;
		height: 38px;
		flex: none;
		place-items: center;
		border-radius: 8px;
		border: 1px solid var(--seam);
		background: var(--panel-raised);
		color: var(--text-dim);
		font-family: var(--font-mono);
		font-size: 10px;
		font-weight: 700;
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
		border: 1px solid var(--seam);
		border-radius: 10px;
	}
	.saved-row > div:first-child {
		display: grid;
		gap: 2px;
	}
	.saved-row small {
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
	}
	.label-input {
		border: 0;
		background: transparent;
		color: var(--text);
		font-weight: 700;
	}
	.row-actions {
		justify-content: flex-start;
	}
	.empty {
		color: var(--text-faint);
		font-size: 12px;
	}
	.source-pill,
	.chips span,
	.recommendation > span {
		padding: 5px 8px;
		border-radius: 999px;
		border: 1px solid var(--seam);
		background: var(--well);
		color: var(--text-dim);
		font-family: var(--font-mono);
		font-size: 10px;
		text-transform: uppercase;
	}
	.editor-panel audio {
		width: 100%;
		margin: 12px 0;
		accent-color: var(--cyan);
	}
	.time-readout {
		display: flex;
		align-items: baseline;
		gap: 8px;
		margin: 14px 0;
		padding: 12px 16px;
		border: 1px solid var(--seam);
		border-radius: 10px;
		background: var(--well);
		box-shadow: inset 0 2px 6px rgba(0, 0, 0, 0.5);
		width: fit-content;
	}
	.time-readout strong {
		font-family: var(--font-mono);
		font-size: 32px;
		font-weight: 500;
		font-variant-numeric: tabular-nums;
		color: var(--amber);
		text-shadow: 0 0 14px var(--amber-dim);
	}
	.time-readout span {
		font-family: var(--font-mono);
		font-size: 13px;
		color: var(--text-faint);
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
		color: var(--text-dim);
		font-size: 11px;
	}
	.bounds-grid input {
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
	}
	.duration-card {
		display: flex;
		justify-content: space-between;
		margin: 14px 0;
		padding: 13px;
		border: 1px solid var(--seam);
		border-radius: 10px;
		background: var(--well);
	}
	.duration-card span {
		color: var(--text-faint);
	}
	.duration-card strong {
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
	}
	.editor-actions {
		justify-content: flex-start;
		gap: 18px;
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
		border: 1px dashed var(--seam);
		border-radius: 10px;
		color: var(--text-faint);
		font-size: 11px;
		text-align: center;
	}
	.assistant-panel {
		border-top: 2px solid var(--amber-dim);
	}
	.assistant-panel.collapsed {
		align-self: start;
	}
	.chat-log p {
		display: grid;
		gap: 4px;
		margin: 0;
		padding: 10px;
		border-radius: 10px;
		background: var(--well);
		color: var(--text-dim);
		font-size: 12px;
	}
	.chat-log p.user {
		background: var(--panel-raised);
		color: var(--text);
	}
	.chat-log b {
		font-family: var(--font-mono);
		font-size: 9px;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--amber);
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
		border: 1px solid rgba(255, 149, 72, 0.35);
		border-radius: 10px;
		background: var(--amber-dim);
	}
	.recommendation > span {
		border-color: rgba(255, 149, 72, 0.35);
		color: var(--amber);
	}
	.recommendation p {
		margin: 0;
		color: var(--text-dim);
		font-size: 12px;
	}
	.assistant-detail {
		display: grid;
		gap: 5px;
		padding-top: 7px;
		border-top: 1px solid rgba(255, 149, 72, 0.2);
	}
	.assistant-detail b {
		color: var(--text);
		font-family: var(--font-mono);
		font-size: 10px;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}
	.assistant-detail ul,
	.assistant-detail ol {
		display: grid;
		gap: 3px;
		margin: 0;
		padding-left: 18px;
		color: var(--text-dim);
		font-size: 11px;
	}
	.assistant-math {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 6px;
	}
	.assistant-math span {
		display: grid;
		gap: 2px;
		padding: 7px;
		border: 1px solid rgba(255, 149, 72, 0.25);
		border-radius: 7px;
		color: var(--text-faint);
		font-family: var(--font-mono);
		font-size: 9px;
		text-transform: uppercase;
	}
	.assistant-math strong {
		color: var(--text);
		font-size: 12px;
		text-transform: none;
	}
	.assistant-bound {
		padding: 7px;
		border-radius: 7px;
		background: var(--well);
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
	}
	.warning-list {
		color: var(--amber);
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
		border: 1px solid var(--seam);
		border-radius: 10px;
		background: var(--panel-raised);
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
		border-radius: 6px;
		background: var(--well);
		color: var(--cyan);
		font-family: var(--font-mono);
		font-weight: 700;
	}
	.timeline-item header div {
		display: grid;
	}
	.timeline-item small {
		color: var(--text-faint);
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
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
		gap: 8px;
		padding: 13px;
		border: 1px dashed var(--seam);
		border-radius: 10px;
		color: var(--text-dim);
	}
	.transition-card strong {
		font-family: var(--font-mono);
		font-size: 12px;
		color: var(--text);
	}
	.meter-row {
		display: grid;
		gap: 5px;
	}
	.meter {
		--fill: 0%;
		width: 100%;
		height: 5px;
		border-radius: 3px;
		background: var(--well);
		overflow: hidden;
	}
	.meter span {
		display: block;
		width: var(--fill);
		height: 100%;
		background: linear-gradient(90deg, var(--amber), var(--cyan));
	}
	.transition-card > div {
		display: flex;
		gap: 5px;
	}
	.transition-card input {
		width: 70px;
		font-family: var(--font-mono);
	}
	.wide {
		min-width: 100%;
		text-align: center;
	}
	.mix-meta input {
		flex: 1;
		font-family: var(--font-display);
		font-size: 18px;
		font-weight: 600;
	}
	.mix-meta span {
		color: var(--text-faint);
		font-family: var(--font-mono);
		font-size: 11px;
		font-variant-numeric: tabular-nums;
	}
	.auto-mix {
		display: grid;
		grid-template-columns: auto minmax(150px, 0.6fr) minmax(220px, 1fr) minmax(300px, 1.2fr) auto;
		align-items: center;
		gap: 9px;
		padding-top: 14px;
		border-top: 1px solid var(--seam);
	}
	.auto-mix h3 {
		font-family: var(--font-display);
		font-weight: 600;
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
