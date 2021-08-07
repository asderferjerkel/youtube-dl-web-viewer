const header = document.getElementById("header");
const playerContainer = document.getElementById("player");
const player = playerContainer.querySelector("video");
const infoContainer = document.getElementById("info");
const info = infoContainer.querySelector(".info");
const descriptionContainer = info.querySelector(".description-container");
const searchContainer = document.getElementById("search");
const controls = document.getElementById("controls");
let playlistList = document.getElementById("playlists");
let videoList = document.getElementById("videos");
let listPadding = 0; // Initial

const pageTitle = document.title; // Original when no video
const titleSuffix = " | ytdl-web"; // Concat with video title

let thumbFormat = 'jpg'; // Default fallback format

let current = {
	video: undefined, // Current video
	playlist: [], // Current playlist contents, indexed by play order
	index: undefined, // Map of video ID: index for the current playlist
	shuffledPlaylist: undefined, // Shuffled playlist
	shuffledIndex: undefined // Map for the shuffled playlist
};
current.playlist.id = undefined; // Current playlist ID


document.addEventListener("DOMContentLoaded", (event) => {
	// Occasionally check tasks if logged in and database ready
	if (apiAvailable) {
		lazyUpdateStatus();
	}
	
	// Calculate padding on lists for scrolling
	// (assuming same for all)
	listPadding = window.getComputedStyle(videoList.parentNode, null).getPropertyValue("padding-top").replace("px", "");
	
	// Test browser format support for thumbnails
	function testImageFormat(format, callback) {
		const testImages = {
			webpLossy: "data:image/webp;base64,UklGRiIAAABXRUJQVlA4IBYAAAAwAQCdASoBAAEADsD+JaQAA3AAAAAA"
		};
		let img = new Image();
		img.onload = function() {
			// True if has dimensions
			let result = (img.width > 0) && (img.height > 0);
			callback(format, result);
		};
		img.onerror = function() {
			callback(format, false);
		};
		img.src = testImages[format];
	};
	
	// Test webp support
	testImageFormat("webpLossy", (format, supported) => {
		if (supported) {
			thumbFormat = 'webp';
		}
	});
	
	// Load a video with unknown playlist
	async function loadVideoPrePlaylist(videoID) {
		// Load video without adding to history, wait for playlist ID
		await loadVideo(videoID, false);
		// Select playlist
		selectItem("playlist", current.video.folder_id);
		// Load playlist, select video
		loadPlaylist(current.video.folder_id);
	}
	
	// Load video/playlist from URL when page loaded
	if (loadItem.type == "p") {
		selectItem("playlist", loadItem.id);
		// Load playlist without adding to history
		loadPlaylist(loadItem.id, false);
	} else if (loadItem.type == "v") {
		loadVideoPrePlaylist(loadItem.id);
	}
	
	// Load from state when history navigated
	window.addEventListener("popstate", (event) => {
		if (event.state !== null) {
			// todo: once added current.folder (done as current.playlist.id), if playlist hasn't changed between pages (current.folder = event.state.playlistID w/e), don't reload playlist, just mark selected appropriate vid
			// treat video and playlist separately: load playlist if different, load video if exists; if no playlist loaded unload it, if no video loaded unload it
			// eventually consider adding in folder list: if can load video, has playlist, but not in list of playlists, don't display the playlist
			//   - maybe just make life easier and load folders after video + playlist
			if (event.state.type === "playlist") {
				// Playlist (but no video) loaded
				unloadCurrent("video");
				selectItem("playlist", event.state.id);
				// Load playlist without adding to history
				loadPlaylist(event.state.id, false);
			} else if (event.state.type === "video") {
				// Video (implies playlist) loaded
				loadVideoPrePlaylist(event.state.id);
			}
		} else {
			// No video loaded for history entry
			unloadCurrent("video");
			unloadCurrent("playlist");
		}
	});
	
	// Search/close clicked
	header.querySelectorAll(".toggle-search button").forEach((button) => {
		button.addEventListener("click", () => {
			// Toggle each search/close button
			header.querySelectorAll(".toggle-search").forEach((element) => {
				element.classList.toggle("toggled");
			});
			// Toggle search bar
			searchContainer.classList.toggle("hidden");
			
			const searchInput = searchContainer.querySelector(".search-query");
			if (!searchContainer.classList.contains("hidden")) {
				// Search opened, focus on input if <3 characters entered
				if (searchInput.value.length < 3) {
					searchInput.focus();
				}
			} else {
				// Search closed, deselect input to hide keyboard on mobile
				searchInput.blur();
			}
		});
	});
	
	// Search query entered
	/*
	listen for changes, if now >3 characters, search for results
	in showResults, add listener for clicked outside results to hide them (but keep search bar)
	clicking on search bar again (listen for focus not click, as opening search doesn't trigger click on it) should show results again
	*/
	
	// Playlist clicked
	playlistList.querySelectorAll(".playlist").forEach(function(playlist) {
		playlist.addEventListener("click", function() {
			// Select self without scrolling to
			let id = selectItem("playlist", null, this, false);
			// Load playlist
			loadPlaylist(id);
		});
	});
	
	// Manual play button clicked
	playManual.addEventListener("click", () => {
		playVideo();
	});
	
	// Next/previous clicked
	controls.querySelector(".next").addEventListener("click", () => {
		changeVideo("next");
	});
	controls.querySelector(".previous").addEventListener("click", () => {
		changeVideo("previous");
	});
	
	// Autoplay toggled
	autoplayButton.addEventListener("click", () => {
		// Autoplay on <-> off
		let value = (displayPrefs["autoplay"] ? false : true);
		updatePrefs("autoplay", value);
	});
	
	// Shuffle toggled
	shuffleButton.addEventListener("click", () => {
		// Shuffle on <-> off
		let shuffle = (displayPrefs["shuffle"] ? false : true);
		updatePrefs("shuffle", shuffle);
		if (shuffle && current.playlist.id !== undefined) {
			// Shuffle on & playlist loaded, shuffle now
			[current.shuffledPlaylist,
			 current.shuffledIndex] = shufflePlaylist();
		}
	});
	
	// Change sort by/direction
	function changeSort(value, isDirection = false) {
		// Pref to change
		let pref = (isDirection ? "sort_direction" : "sort_by");
		updatePrefs(pref, value);
		if (current.playlist.id !== undefined) {
			// Playlist loaded, reload it
			loadPlaylist(current.playlist.id);
		}
	}
	
	// Sort by changed
	sortSelect.addEventListener("change", function() {
		changeSort(this.value);
	});
	// Sort asc clicked (-> desc)
	ascButton.addEventListener("click", () => {
		changeSort("desc", true);
	});
	// Sort desc clicked (-> asc)
	descButton.addEventListener("click", () => {
		changeSort("asc", true);
	});
		
	// "Show more"/"show less" clicked
	infoContainer.querySelector(".more-link").addEventListener("click", () => {
		fullDescription(true);
	});
	infoContainer.querySelector(".less-link").addEventListener("click", () => {
		fullDescription(false);
	});
	
	// Video ended
	player.addEventListener("ended", () => {
		if (displayPrefs.autoplay) {
			changeVideo("next");
		} else {
			// Show manual play button to replay
			playManual.classList.remove("hidden");
		}
	});
	
	// Window resized
	let resizeTimer;
	window.addEventListener("resize", () => {
		// If not already expanded
		if (!fullHeight) {
			clearTimeout(resizeTimer); // Reset delay if resize ongoing
			// Once resize stopped for 300ms, test description overflow
			resizeTimer = setTimeout(descriptionOverflow, 300);
		}
	});
});


// Reload and display the list of playlists
async function loadFolders() {
	let folders = await loadJSON("playlists");
	// Sort folders by key and map values to array
	// todo: map instead, keeps order
	let foldersSort = Object.keys(folders.data).sort().map((index) => folders.data[index]);
	if (foldersSort.length === 0) {
		// No folders, replace with placeholder
		unloadCurrent("folders");
	} else {
		displayFolders(foldersSort);
	}
}

function displayFolders(folders) {
	const template = document.getElementById("template-playlist");
	// Create empty list of folders from container
	let newPlaylistList = playlistList.cloneNode(false);
	// Add each folder to list
	folders.forEach((folder) => {
		let folderElement = template.content.firstElementChild.cloneNode(true);
		// Populate template
		folderElement.setAttribute("data-playlist", folder.id);
		folderElement.querySelector(".number")
			.textContent = folder.video_count;
		folderElement.querySelector(".name").textContent = folder.folder_name;
		
		// Playlist clicked
		folderElement.addEventListener("click", function() {
			// Select self without scrolling to
			let id = selectItem("playlist", null, this, false);
			// Load playlist
			loadPlaylist(id);
		});
		newPlaylistList.appendChild(folderElement);
	});
	
	// Replace existing folder list, clearing listeners
	playlistList.parentNode.replaceChild(newPlaylistList, playlistList);
	playlistList = newPlaylistList;
		
	if (current.playlist.id !== undefined) {
		// A playlist was previously loaded, select it and reload
		let element = selectItem("playlist", current.playlist.id)
		loadPlaylist(current.playlist.id);
	} else {
		// No previous playlist to load, but > 0 playlists
		let placeholder = videoList.querySelector(".placeholder");
		if (placeholder !== null) {
			// Update playlist placeholder text
			placeholder.textContent = "Select a playlist";
		}
	}
}


// Load and display a playlist by its ID
async function loadPlaylist(playlistID, addHistory = true) {
	let playlist = await loadJSON("playlist", playlistID,
								  displayPrefs.sort_by,
								  displayPrefs.sort_direction);
	current.playlist.length = 0; // Empty
	// Create array by play order
	Object.keys(playlist.data).forEach(
		key => current.playlist.push(playlist.data[key]));
	if (current.video === undefined) {
		// Only update page URL if no video loaded
		window.history[addHistory ? "pushState" : "replaceState"](
				{"type": "playlist", "id": playlistID},
				"", // title
				baseUrl + "p/" + playlistID);
	}
	if (playlist.length === 0) {
		// Empty playlist, replace with placeholder
		unloadCurrent("playlist");
	} else {
		current.playlist.id = playlistID;
		displayPlaylist(current.playlist);
	}
}

function displayPlaylist(playlist) {
	// Clear existing playlist
	current.index = {};
	current.shuffledPlaylist = undefined;
	current.shuffledIndex = undefined;
	const template = document.getElementById("template-video");
	// Create empty playlist from container
	let newVideoList = videoList.cloneNode(false);
	// Add each video to list
	playlist.forEach((video, index) => {
		// Create inverse video.id: index mapping to look up play order by ID
		current.index[video.id] = index;
		
		let videoElement = template.content.firstElementChild.cloneNode(true);
		// Populate template
		videoElement.setAttribute("data-video", video.id);
		videoElement.querySelector(".position").textContent = index + 1;
		videoElement.querySelector(".duration").textContent = video.duration;
		videoElement.querySelector(".number").textContent = index + 1;
		videoElement.querySelector(".name").textContent = video.title;
		
		videoElement.addEventListener("click", function() {
			// Video clicked
			// Select self without scrolling to
			let id = selectItem("video", null, this, false);
			if (displayPrefs.shuffle) {
				// Reshuffle playlist, starting from clicked video
				[current.shuffledPlaylist,
				current.shuffledIndex] = shufflePlaylist(id);
			}
			// Load video
			loadVideo(id);
		});
		
		// Add video to list
		newVideoList.appendChild(videoElement);
	});
	
	// Replace existing playlist, clearing listeners
	videoList.parentNode.replaceChild(newVideoList, videoList);
	videoList = newVideoList;
	
	// Observe visibility changes in videos to load thumbs
	if (typeof(observer.disconnect) !== "undefined") {
		// Disconnect any existing observer
		observer.disconnect();
	}
	observer = createObserver();
	videoList.querySelectorAll(".thumb").forEach((thumb) => {
		observer.observe(thumb);
	});
	
	if (displayPrefs.shuffle) {
		// Shuffle enabled, generate shuffled playlist
		[current.shuffledPlaylist, current.shuffledIndex] = shufflePlaylist();
	}
	
	if (current.video !== undefined &&
		current.video.folder_id === current.playlist.id) {
		// Current video is from this playlist, select it
		selectItem("video", current.video.id);
	}
}


// Load, display and play a video by its ID
// If addHistory = false, replaces current entry instead of adding
async function loadVideo(videoID, addHistory = true) {
	let video = await loadJSON("video", videoID);
	current.video = video.data;
	// Update page URL
	window.history[addHistory ? "pushState" : "replaceState"](
			{"type": "video", "id": videoID},
			"", // title
			baseUrl + "v/" + videoID);
	// Browsers don't support history.pushState title so set directly
	document.title = current.video.title + titleSuffix;
	displayVideo(current.video);
}

function displayVideo(video) {
	// Remove current poster if present
	player.removeAttribute("poster");
	// Remove current source
	let source = player.getElementsByTagName("source")[0];
	if (source !== undefined) {
		player.removeChild(source);
	}
	// Create new source
	var newSource = document.createElement("source");
	newSource.src = video.path;
	newSource.type = video.video_format;
	player.appendChild(newSource);
	// Load source
	player.load();
	// Hide placeholder if present
	playerContainer.querySelector(".placeholder").classList.add("hidden");
	// Hide manual play button early if present
	playManual.classList.add("hidden");
	
	// Hide info box until ready to avoid multiple reflow
	infoContainer.classList.add("hidden");
	
	/**
	Add metadata
	  Normal fields (metadata can be inserted directly):
	    key: json field
	    display: selector to hide if data missing
	    contents: selector to fill with data (if different from display)
	*/
	let metadataFields = {
		title: {
			display: ".title" },
		uploader: {
			display: ".uploader" },
		upload_date: {
			display: ".date",
			contents: ".date-value" },
		vcodec: {
			display: ".codec" }
	};
	
	for ([key, field] of Object.entries(metadataFields)) {
		let contentField = (field.contents !== undefined ? field.contents : field.display);
		if (video[key] !== null) {
			// Field has data, fill and show
			info.querySelector(contentField).textContent = video[key];
			info.querySelector(field.display).classList.remove("hidden");
		} else {
			// No data for field, hide and empty
			info.querySelector(contentField).textContent = "";
			info.querySelector(field.display).classList.add("hidden");
		}
	};
	
	/**
	List fields
	  key: json array field
	  display: list of selectors to hide if data missing
	  contents: selector to fill with data
	*/
	let listFields = {
		categories: {
			display: [".categories-label", ".categories"],
			contents: ".categories" },
		tags: {
			display: [".tags-label", ".tags"],
			contents: ".tags" }
	};
	
	Object.entries(listFields).forEach(function([key, field]) {
		// Default empty and hide
		let fieldData = "";
		let fieldHidden = true;
		if (Array.isArray(video[key]) && video[key].length > 0) {
			// List has items
			// Remove invalid/empty items, comma-separate and show
			fieldData = video[key].filter(Boolean).join(", ");
			fieldHidden = false;
		}
		
		info.querySelector(field.contents).textContent = fieldData;
		field.display.forEach(selector => {
			info.querySelector(selector).classList[fieldHidden ? "add" : "remove"]("hidden");
		});
	});
	
	// Special case fields:
	// Uploader link (still hidden if no uploader name)
	if (video.uploader_url !== null) {
		info.querySelector(".uploader").href = video.uploader_url;
	}
	
	// Views (add separators)
	if (video.view_count !== null) {
		info.querySelector(".views-value").textContent = Number(video.view_count).toLocaleString();
		info.querySelector(".views").classList.remove("hidden");
	} else {
		info.querySelector(".views").classList.add("hidden");
		info.querySelector(".views-value").textContent = "";
	}
	
	// Original URL
	let link = info.querySelector(".link");
	if (video.video_url !== null) {
		link.href = video.video_url;
		link.classList.remove("hidden");
	} else {
		link.classList.add("hidden");
		link.href = "";
	}
	
	/**
	Star rating
	  Stars in image have defined widths and gaps, so we can calculate the
	  inset to apply to ignore gaps and only clip stars:
	  
	  0% 16 21 37 42 58 63 79 84 100%
	  |   | |   | |   | |   | |   |
	
	  e.g. 1.5 stars is 29% (71% inset)
	*/
	if (video.average_rating !== null) {
		let inset = Math.round((100 - ((video.average_rating * 16) + (Math.floor(video.average_rating) * 5))) * 10) / 10; // * 10, round, / 10 gives 1 decimal place
		inset = (inset <= 0 ? 0 : inset); // Avoid -5% inset on a perfect 5*
		info.querySelector(".stars-filled").style.clipPath = "inset(0 " + inset + "% 0 0)";
		// Number too
		let rating = Math.round(video.average_rating * 100) / 100;
		info.querySelector(".rating-value").textContent = rating;
		info.querySelector(".rating").classList.remove("hidden"); // Grid for overlaying images
	} else {
		// Default to empty stars & hide
		info.querySelector(".rating").classList.add("hidden");
		info.querySelector(".stars-filled").style.clipPath = "inset(0 100% 0 0)";
		info.querySelector(".rating-value").textContent = "";
	}
	
	// Date (if uploaded missing, get downloaded from modtime)
	if (video.upload_date === null && video.modification_time !== null) {
		info.querySelector(".date-value").textContent = video.modification_time;
		info.querySelector(".date-type").textContent = "Downloaded";
		info.querySelector(".date").classList.remove("hidden");
	} else {
		// Default label
		info.querySelector(".date-type").textContent = "Uploaded";
		// Date downloaded as tooltip
		info.querySelector(".date").title = "Downloaded " + video.modification_time;
	}
	
	// Resolution and/or fps (add suffixes and concat)
	let height = (video.height !== null ? video.height + "p" : null);
	let fps = (video.fps !== null
			? Math.round(video.fps * 100) / 100 + "fps" : null);
	let format = [height, fps].filter(Boolean).join(" ");
	info.querySelector(".resolution-fps").textContent = format; // Empty if both missing
	if (format !== "") {
		// Show if at least one of resolution, format or codec are present
		info.querySelector(".format").classList.remove("hidden");
	}
	
	// Description (replace newlines with <br>)
	let description = descriptionContainer.querySelector(".description");
	if (video.description !== null) {
		description.innerText = video.description; // Insert safely
		description.classList.remove("hidden");
	} else {
		description.classList.add("hidden");
		description.innerText = "";
	}
	
	// Show info container
	infoContainer.classList.remove("hidden");
	// Don't fade description if previously expanded
	// todo: fix this. only do on small screens?
	if (!fullHeight) {
		// Set description container to overflow
		fullDescription(false);
		// Test overflow: if yes, fade description and display "show more" link
		// 				  if no, remove fade and hide "show more" link
		descriptionOverflow();
	}
	
	// Play video
	playVideo();
}


// Load and display thumbnails from a Map of videoID: element
const thumbsPerRq = 10;
async function loadThumbs(thumbQueue) {
	let videoIDs = Array.from(thumbQueue.keys());
	// Split into chunks for smaller API responses
	videoIDs = [...Array(Math.ceil(videoIDs.length / thumbsPerRq))]
				.map((_, chunkIndex) => 
					videoIDs.slice(
						chunkIndex * thumbsPerRq,
						(chunkIndex * thumbsPerRq) + thumbsPerRq
					)
				);
	
	// Request each chunk in turn
	await Promise.all(videoIDs.map(async (chunk) => {
		const thumbs = await loadJSON("POST", chunk, "thumbs", thumbFormat);
		// Loop through requested IDs
		for (videoID of chunk) {
			let element = thumbQueue.get(videoID);
			// Add image data if returned
			if (videoID in thumbs.data) {
				element.src = thumbs.data[videoID].d;
			}
			// Stop observing this video
			// (also prevents retry if no thumb returned)
			observer.unobserve(element);
		};
	}));
};

// Watch for changes in visible playlist items and trigger thumbnail loads
let observer = {};
function createObserver(rootElement) {
	obs = new IntersectionObserver(intersectionChanged, {
		root: rootElement,
		threshold: 0.2, // Trigger when proportion visible
		delay: 100 // Don't trigger events too often
	});
	return obs;
};

const numRecentThumbs = 25; // Load the newest x intersecting thumbs
let pendingThumbs = [];
let intersectionTimer;
function intersectionChanged(entries, observer) {
	entries.forEach((entry) => {
		if (entry.isIntersecting) {
			// Element now within bounds, add to queue
			const thumbElement = entry.target;
			const videoID = thumbElement.parentNode.parentNode
										.getAttribute("data-video") << 0;
			pendingThumbs.push([videoID, thumbElement]);
		}
	});
	
	function thumbsFromPending() {
		// Get most recent thumbs from queue
		const recentThumbs = new Map([...pendingThumbs.slice(-numRecentThumbs)]);
		// Clear queue and load thumbs
		pendingThumbs.length = 0;
		loadThumbs(recentThumbs);
	};
	
	if (pendingThumbs.length > 0) {
		// Have thumbs queued, reset delay
		clearTimeout(intersectionTimer);
		// Once no more thumbs queued for 200ms, get thumbs
		// (with queue at time of calling, in case more added)
		intersectionTimer = setTimeout(thumbsFromPending, 200);
	}
};


// Search metadata fields for videos
let abortController = null;
async function searchVideos(field, query) {
	if (abortController) {
		// Cancel the previous request if pending
		abortController.abort();
		abortController = null;
	}
	
	abortController = new AbortController();
	try {
		const results = await loadJSON(abortController.signal,
									   "POST", query, "search", field);
		console.log(results); // todo: delete
		return results.data; // also
		//displaySearchResults(results.data);
	} catch(err) {
		// Request aborted
	} finally {
		abortSearchController = null;
	}
};

function displaySearchResults(results) {
	// clear existing results (same clonenode so clears listeners)
	// display matches: template w/ thumb placeholder (push into queue w/ ID), title, snippet, click listener to loadVideo
	// load thumbs
	
	// then the search button listener opens the field and focuses (with existing search if not changed)
	// unfocusing on the field hides the list (ie once clicked? or just hide in the click listener)
	// or tapping anywhere but it
	// or search icon turns into an X
	// have fixed max height but can scroll
	
	// if that works in the right order then sack off this indexed dict bs
};


// Play the currently-loaded video
const playManual = playerContainer.querySelector(".play-manual");
function playVideo() {
	// Play video
	player.play()
	.then(() => {
		// Hide manual play button if present
		playManual.classList.add("hidden");
		// Set up mediaSession for media notification
		if ("mediaSession" in navigator) {
			let thumbnail = [];
			if (current.video.thumbnail !== null &&
				current.video.thumbnail_format !== null) {
				thumbnail = [{
					src: current.video.thumbnail,
					sizes: "1920x1080", // hardcoded lol
					type: current.video.thumbnail_format
				}];
			}
			
			navigator.mediaSession.metadata = new MediaMetadata({
				title: current.video.title,
				artist: (current.video.uploader !== null
					  ? current.video.uploader : "ytdl-web"),
				album: current.video.folder_name,
				artwork: thumbnail
			});
		}
	})
	.catch(error => {
		// Playback failed (probably user hasn't interacted with page)
		console.log("Autoplay not allowed:", error);
		// Set thumbnail as placeholder
		if (current.video !== undefined && current.video.thumbnail !== null) {
			player.poster = current.video.thumbnail;
		}
		// Add manual play button
		playManual.classList.remove("hidden");
	});
}


// Change to the next or previous video
async function changeVideo(direction = "next") {
	// Select normal or shuffled playlist depending on prefs
	playlist = (displayPrefs.shuffle
			 ? current.shuffledPlaylist : current.playlist);
	index = (displayPrefs.shuffle ? current.shuffledIndex : current.index);
	if (current.video !== undefined) {
		// Video currently loaded
		let newIndex = (direction === "next"
					 ? index[current.video.id] + 1
					 : index[current.video.id] - 1);
		if (playlist[newIndex] !== undefined) {
			console.log("Playing " + direction + " video");
			let newVideoID = playlist[newIndex].id;
			// Select video
			selectItem("video", newVideoID);
			// Load video
			loadVideo(newVideoID);
		} else {
			// No more videos in playlist
			console.log("No more videos in playlist");
			// Unload video
			unloadCurrent("video");
		}
		
	} else {
		// No previous video loaded
		console.log("No previous video loaded")
		if (current.playlist.id === undefined) {
			// No playlist loaded
			// todo: have an array of playlists. take element out of selectItem if not using it (+ shift a brace down i think)
			// Select first playlist
			let firstPlaylist = playlistList.querySelector(".playlist");
			if (firstPlaylist !== null) {
				console.log("Loading first playlist");
				// Select playlist
				let id = selectItem("playlist", null, firstPlaylist);
				// Load playlist
				await loadPlaylist(id);
			} else {
				console.log("No playlists loaded");
			}
		}
		
		// Play first or last video in playlist
		// If shuffle enabled, will repeat previous shuffle order until
		// reshuffled by toggling off & on or clicking a different video
		console.log("Playing " + (direction === "next"
							   ? "first" : "last") + " video");
		let newVideoID = (direction === "next"
					   ? playlist[0].id
					   : playlist[playlist.length - 1].id);
		// Select video
		selectItem("video", newVideoID);
		// Load video
		loadVideo(newVideoID);
	}
}


/**
Unload the current video, playlist or folder list
  item = "video":	 Stop playback, unload source, replace with placeholder
					 Unsets current.video
  item = "playlist": Unload playlist, replace with placeholder
					 Unsets current.playlist, current.index
  item = "folders":  Unload folder list, replace with placeholder
					 Implies unloadCurrent("playlist")
*/
function unloadCurrent(item = "video") {
	if (item === "video") {
		// Remove poster
		player.removeAttribute("poster");
		// Remove source
		let source = player.getElementsByTagName("source")[0];
		if (source !== undefined) {
			player.removeChild(source);
		};
		// Reload player without source (+ dismisses media notification)
		player.load();
		// Hide manual play button
		playManual.classList.add("hidden");
		// Show placeholder
		playerContainer.querySelector(".placeholder").classList.remove("hidden");
		// Deselect video
		selectItem("video");
		// Unset video
		current.video = undefined;
		// Hide infobox
		infoContainer.classList.add("hidden");
		// Clear metadata
		info.querySelectorAll(".title, .uploader, .views-value, .rating-value, "
							+ ".date-value, .format .meta-label, .description, "
							+ ".tags, .categories").forEach(
								element => element.textContent = "");
		info.querySelectorAll(".uploader, .link").forEach(
								link => link.href = "");
		info.querySelector(".stars-filled")
							   .style.clipPath = "inset(0 100% 0 0)";
		// Reset page title
		document.title = pageTitle;
	} else if (item === "playlist" || item === "folders") {
		// Empty playlists
		current.playlist.length = 0;
		current.playlist.id = undefined;
		current.index = undefined;
		current.shuffledPlaylist = undefined;
		current.shuffledIndex = undefined;
		// Deselect playlist
		selectItem("playlist");
		
		// Create list placeholder
		function insertPlaceholder(list, text) {			
			let emptyList = list.cloneNode(false);
			let placeholderElement = document.createElement("div");
			placeholderElement.className = "placeholder";
			placeholderElement.textContent = text;
			emptyList.appendChild(placeholderElement);
			// Replace current list
			list.parentNode.replaceChild(emptyList, list);
			// Return placeholder
			return emptyList;
		}
		
		if (item === "folders") {
			// Replace folder list
			playlistList = insertPlaceholder(playlistList, "No playlists");
		}
		// Unload folders implies playlist
		videoList = insertPlaceholder(videoList,
			(item === "playlist" ? "Select a playlist" : "No videos"));
	}
}


/**
Shuffles current playlist and index
  Starts from videoID if supplied, or current video if loaded
  Returns shuffledPlaylist and shuffledIndex
*/
function shufflePlaylist(videoID = null) {
	// Clone current.playlist
	let shuffledPlaylist = [...current.playlist];
	let shuffledIndex = {};
	
	let excludeFirst = 0;
	let randomRange = 1;
	if (current.video !== undefined || videoID !== null) {
		// Prioritise videoID if supplied, as clicking a new video shuffles
		// starting from it before current.video is updated
		let id = (videoID !== null ? videoID : current.video.id);
		// Copy current video
		let currentIndex = current.index[id]
		let currentVideo = current.playlist[currentIndex];
		// Delete current video from playlist
		shuffledPlaylist.splice(currentIndex, 1);
		// Readd from copy at index 0
		shuffledPlaylist.splice(0, 0, currentVideo);
		// Map ID to index
		shuffledIndex[id] = 0;
		
		// Exclude first video from shuffle
		excludeFirst = 1;
		randomRange = 0;
	}
	
	// Fisher-Yates shuffle
	// Loop from last index to 0 (1 if excluding first)
	for (var temp, randomIndex, lastUnshuffled = current.playlist.length;
		(lastUnshuffled--) - excludeFirst;) {
		// Generate a random index from the unshuffled part of the array
		// Generates 0 (1 if excluding first) to lastUnshuffled
		randomIndex = (excludeFirst + (Math.random()
					* (lastUnshuffled + randomRange)))
					<< 0; // Bitwise shift coerces to integer
		// Swap random item with highest unshuffled item
		temp = shuffledPlaylist[randomIndex];
		shuffledPlaylist[randomIndex] = shuffledPlaylist[lastUnshuffled];
		shuffledPlaylist[lastUnshuffled] = temp;
		// Add video ID to index
		shuffledIndex[shuffledPlaylist[lastUnshuffled].id] = lastUnshuffled;
		// Random item now shuffled, repeat with remainder of unshuffled
	};
	
	return [shuffledPlaylist, shuffledIndex];
}


/**
Mark or unmark a list item (video or playlist) as selected
  Previously-selected item of type = ["playlist", "video"] will be unmarked
  itemID or element supplied: item will be marked selected
  itemID supplied: returns list item's element
*/
function selectItem(type = "playlist", itemID = null,
					element = null, scrollTo = true) {
	let list = (type === "video" ? videoList : playlistList);
	let attribute = (type === "video" ? "data-video" : "data-playlist");
	let currentlySelected = list.querySelector(".selected");
	if (currentlySelected !== null) {
		// Unmark currently selected item
		currentlySelected.classList.remove("selected");
	}
	if (itemID !== null) {
		// ID supplied, get element by data-attribute
		element = list.querySelector("[" + attribute + "='" + itemID + "']")
	}
	if (element !== null) {
		// Mark item selected
		element.classList.add("selected");
		if (scrollTo) {
			// Scroll into view
			//element.scrollIntoView({block: "nearest"});
			list.scrollTop = element.offsetTop - listPadding;
		}
		if (itemID !== null) {
			// ID supplied, return element
			return element;
		} else {
			// Element supplied, return numeric ID
			return (+element.getAttribute(attribute));
		}
	}
}


/**
Toggle displaying full or clipped description
  show = true: full-height description & "show less"
  show = false: description overflows & "show more"
*/
let fullHeight = true; // Page load default (todo: fix all this, mayb only show on mob)
function fullDescription(show = true) {
	fullHeight = (show ? true : false);
	infoContainer.classList[show ? "add" : "remove"]("full-height");
}

// Show "show more" if description overflows container
const showMore = infoContainer.querySelector(".show-more");
function descriptionOverflow() {
	if (!fullHeight) {
		// Container height is limited, test overflow
		if (descriptionContainer.offsetHeight <
			descriptionContainer.scrollHeight) {
			// Description overflows, show links
			showMore.classList.remove("hidden");
		} else {
			// Description fits, hide fade and links
			fullDescription(true);
			showMore.classList.add("hidden");
		}
	}
}


/**
Set display preferences for the current session (if logged in) and page
  pref = ["autoplay", "shuffle"]: value = [true, false]
  pref = "sort_direction": value = ["asc", "desc"]
  pref = "sort_by": allowed values from app config
*/
const autoplayButton = controls.querySelector(".autoplay");
const shuffleButton = controls.querySelector(".shuffle");
const sortSelect = controls.querySelector(".sort-by");
const ascButton = controls.querySelector(".asc");
const descButton = controls.querySelector(".desc");
async function updatePrefs(pref, value) {
	// Update for current page load
	displayPrefs[pref] = value;
	
	let prefValue = value;
	if (pref === "autoplay" || pref === "shuffle") {
		let control = (pref === "autoplay" ? autoplayButton : shuffleButton);
		// Update button appearance to new value
		control.classList[displayPrefs[pref] ? "add" : "remove"]("enabled");
		// Convert for API
		prefValue = (prefValue ? "1" : "0");
	} else if (pref === "sort_direction") {
		// Show asc if now asc; desc if now desc
		ascButton.classList[displayPrefs[pref] === "asc"
						  ? "remove" : "add"]("hidden");
		descButton.classList[displayPrefs[pref] === "desc"
						  ? "remove" : "add"]("hidden");
	};
	
	if (apiAvailable) {
		// Update for session
		await loadJSON("prefs", pref, prefValue);
	} else {
		console.log("Not logged in, preferences stored only for this page load");
	}
}


// Set up media notification controls
function updatePositionState() {
	if ("mediaSession" in navigator &&
		"setPositionState" in navigator.mediaSession) {
		navigator.mediaSession.setPositionState({
			duration: player.duration,
			playbackRate: player.playbackRate,
			position: player.currentTime
		});
	}
}

// Default seconds to skip with seek buttons
let defaultSkipTime = 10;
if ("mediaSession" in navigator) {
	navigator.mediaSession.setActionHandler("play", async function() {
		// No need to set metadata again as notification only shown
		// when a video is already loaded and playing/paused
		await player.play();
		// Manually update playbackState for consistency between
		// player and notification
		navigator.mediaSession.playbackState = "playing";
	});
	navigator.mediaSession.setActionHandler("pause", async function() {
		player.pause();
		navigator.mediaSession.playbackState = "paused";
	});
	navigator.mediaSession.setActionHandler("nexttrack", function() {
		changeVideo("next");
	});
	navigator.mediaSession.setActionHandler("previoustrack", function() {
		changeVideo("previous");
	});
	navigator.mediaSession.setActionHandler("seekforward", function(event) {
		const skipTime = event.seekOffset || defaultSkipTime;
		// Max skip to end of video
		player.currentTime = Math.min(player.currentTime +
									  skipTime, player.duration);
	});
	navigator.mediaSession.setActionHandler("seekbackward", function(event) {
		const skipTime = event.seekOffset || defaultSkipTime;
		// Min skip to start of video
		player.currentTime = Math.max(player.currentTime - skipTime, 0);
	});
	try { // Notification closed (only recent browsers)
		navigator.mediaSession.setActionHandler("stop", function() {
			// Unload video
			unloadCurrent("video");
		});
	} catch(error) {
		console.log("mediaSession action 'stop' " +
					"not supported by this browser");
	};
	try { // Notification seek to (only recent browsers)
		navigator.mediaSession.setActionHandler("seekto", function(event) {
			if (event.fastSeek && ("fastSeek" in player)) {
				player.fastSeek(event.seekTime);
				return;
			}
			player.currentTime = event.seekTime;
			updatePositionState();
		});
	} catch(error) {
		console.log("mediaSession action 'seekto' " +
					"not supported by this browser");
	};
}