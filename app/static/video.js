// How long (ms) to wait for further user input before firing events
const inputDelay = 200;
// Default seconds to skip with seek buttons if not specified by media
const defaultSkipTime = 10;

const header = document.getElementById("header");

const playerContainer = document.getElementById("player");
const player = playerContainer.querySelector("video");

const infoContainer = document.getElementById("info");
const info = infoContainer.querySelector(".info");
const descriptionContainer = info.querySelector(".description-container");

const searchContainer = document.getElementById("search");
const searchInput = searchContainer.querySelector(".search-query");
const searchField = searchContainer.querySelector(".search-field");
let searchResults = searchContainer.querySelector(".search-results");

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
		const img = new Image();
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
	
	// Load video/playlist from URL when page loaded
	if (loadItem.type == "p") {
		selectItem("playlist", loadItem.id);
		// Load playlist without adding to history
		loadPlaylist(loadItem.id, false);
	} else if (loadItem.type == "v") {
		// Load video and playlist without adding to history
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
			// Toggle search/close button and search bar
			header.classList.toggle("search-toggled");
			
			if (header.classList.contains("search-toggled")) {
				// Search opened, focus & select input
				searchInput.select();
			} else {
				// Search closed, deselect input to hide keyboard on mobile
				searchInput.blur();
			}
		});
	});
	
	// Search input focused, show results
	searchContainer.addEventListener("focusin", showResults);
	
	// Search query entered
	let searchTimer;
	searchInput.addEventListener("input", () => {
		clearTimeout(searchTimer); // Reset delay if still typing
		// Once inputDelay elapsed, run search
		searchTimer = setTimeout(searchVideos, inputDelay);
	});
	
	// Search field changed
	searchField.addEventListener("change", () => {
		// Run search without checking for input change
		searchVideos(false);
	});
	
	// Playlist clicked
	playlistList.querySelectorAll(".playlist").forEach(function(playlist) {
		playlist.addEventListener("click", function() {
			// Select self without scrolling to
			const id = selectItem("playlist", null, this, false);
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
		const autoplay = (displayPrefs["autoplay"] ? false : true);
		updatePrefs("autoplay", autoplay);
	});
	
	// Shuffle toggled
	shuffleButton.addEventListener("click", () => {
		// Shuffle on <-> off
		const shuffle = (displayPrefs["shuffle"] ? false : true);
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
		const pref = (isDirection ? "sort_direction" : "sort_by");
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
	infoContainer.querySelector(".show-more button").addEventListener("click", () => {
		infoContainer.classList.toggle("full-height");
	});
	
	// Keyboard shortcuts
	window.addEventListener("keydown", (event) => {
		// Ignore if search input selected or modifier keys
		if ((event.target !== searchInput) &&
			!(event.ctrlKey || event.altKey || event.metaKey)) {
				switch (event.key) {
					case "?":
						const helpText = "Keyboard shortcuts:\n\n" +
										 "k : play/pause\n" +
										 "j : seek backwards\n" +
										 "l : seek forwards\n" +
										 ", : previous frame\n" +
										 ". : next frame\n" +
										 "p : previous video\n" +
										 "n : next video\n" +
										 "s : stop\n" +
										 "f : fullscreen\n" +
										 "m : mute\n" +
										 "/ : search"
						addMessage(helpText, "keyboard-help");
						break;
					case " ":
					case "k":
						// Toggle play/pause
						player.paused ? playVideo() : player.pause();
						break;
					case "l":
						// Seek forwards
						player.currentTime = Math.min(player.currentTime +
													  defaultSkipTime,
													  player.duration);
						break;
					case "j":
						// Seek backwards
						player.currentTime = Math.max(player.currentTime -
													  defaultSkipTime, 0);
						break;
					case ".":
						// Seek forwards one frame (if paused)
						if (player.paused) {
							player.currentTime = Math.min(player.currentTime +
														  1/current.video.fps,
														  player.duration);
						} else {
							addMessage("Pause video to seek by frame",
									   "seek-help", true);
						}
						break;
					case ",":
						// Seek backwards one frame (if paused)
						if (player.paused) {
							player.currentTime = Math.max(player.currentTime -
														  1/current.video.fps,
														  0);
						} else {
							addMessage("Pause video to seek by frame",
									   "seek-help", true);
						}
						break;
					case "n":
						// Next video
						changeVideo("next");
						break;
					case "p":
						// Previous video
						changeVideo("previous");
						break;
					case "s":
						// Stop video
						unloadCurrent("video");
						break;
					case "f":
						// Toggle fullscreen
						document.fullscreen ? document.exitFullscreen() :
											  player.requestFullscreen();
						break;
					case "m":
						// Toggle mute
						player.muted = player.muted ? false : true;
						break;
					case "/":
						// Open search
						event.preventDefault(); // Don't type /
						header.classList.add("search-toggled");
						searchInput.select();
						break;
				}
		}
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
		if (!infoContainer.classList.contains("full-height")) {
			clearTimeout(resizeTimer); // Reset delay if resize ongoing
			// Once resize stopped for inputDelay, test description overflow
			resizeTimer = setTimeout(descriptionOverflow, inputDelay);
		}
	});
});


// Reload and display the list of playlists
async function loadFolders() {
	const folders = await loadJSON("playlists");
	// Sort folders by key and map values to array
	// todo: map instead, keeps order
	//let foldersSort = Object.keys(folders.data).sort().map((index) => folders.data[index]);
	// todo: ^^delete that already sorted see api
	if (folders.data.length === 0) {
		// No folders, replace with placeholder
		unloadCurrent("folders");
	} else {
		displayFolders(folders.data);
	}
}

function displayFolders(folders) {
	const template = document.getElementById("template-playlist");
	// Create empty list of folders from container
	const newPlaylistList = playlistList.cloneNode(false);
	// Add each folder to list
	folders.forEach((folder) => {
		const folderElement = template.content.firstElementChild
							  .cloneNode(true);
		// Populate template
		folderElement.setAttribute("data-playlist", folder.id);
		folderElement.querySelector(".number")
			.textContent = folder.video_count;
		folderElement.querySelector(".name").textContent = folder.folder_name;
		
		// Playlist clicked
		folderElement.addEventListener("click", function() {
			// Select self without scrolling to
			const id = selectItem("playlist", null, this, false);
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
	const playlist = await loadJSON("playlist", playlistID,
									displayPrefs.sort_by,
									displayPrefs.sort_direction);
	// todo: delete
	//current.playlist.length = 0; // Empty
	// Create array by play order
	//Object.keys(playlist.data).forEach(
	//	key => current.playlist.push(playlist.data[key]));
	current.playlist = playlist.data;
	current.playlist.id = playlistID;
	if (current.video === undefined) {
		// Only update page URL if no video loaded
		window.history[addHistory ? "pushState" : "replaceState"](
				{"type": "playlist", "id": playlistID},
				"", // title
				baseUrl + "p/" + playlistID);
	}
	if (current.playlist.length === 0) {
		// Empty playlist, replace with placeholder
		unloadCurrent("playlist");
	} else {
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
	const newVideoList = videoList.cloneNode(false);
	// Add each video to list
	playlist.forEach((video, index) => {
		// Create inverse video.id: index mapping to look up play order by ID
		current.index[video.id] = index;
		
		const videoElement = template.content.firstElementChild.cloneNode(true);
		// Populate template
		videoElement.setAttribute("data-video", video.id);
		videoElement.querySelector(".position").textContent = index + 1;
		videoElement.querySelector(".duration").textContent = video.d;
		videoElement.querySelector(".number").textContent = index + 1;
		videoElement.querySelector(".name").textContent = video.t;
		
		videoElement.addEventListener("click", function() {
			// Video clicked
			// Select self without scrolling to
			const id = selectItem("video", null, this, false);
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
	// todo: can get the new element from appendChild above and observe there
	if (getThumbs) {
		if (typeof(observer.disconnect) !== "undefined") {
			// Disconnect any existing observer
			observer.disconnect();
		}
		observer = createObserver();
		videoList.querySelectorAll(".thumb").forEach((thumb) => {
			observer.observe(thumb);
		});
	}
	
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
	const video = await loadJSON("video", videoID);
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
	const source = player.getElementsByTagName("source")[0];
	if (source !== undefined) {
		player.removeChild(source);
	}
	// Create new source
	const newSource = document.createElement("source");
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
	const metadataFields = {
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
		const contentField = (field.contents !== undefined
						   ? field.contents : field.display);
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
	const listFields = {
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
			info.querySelector(selector)
				.classList[fieldHidden ? "add" : "remove"]("hidden");
		});
	});
	
	// Special case fields:
	// Uploader link (still hidden if no uploader name)
	if (video.uploader_url !== null) {
		info.querySelector(".uploader").href = video.uploader_url;
	}
	
	// Views (add separators)
	if (video.view_count !== null) {
		info.querySelector(".views-value")
			.textContent = Number(video.view_count).toLocaleString();
		info.querySelector(".views").classList.remove("hidden");
	} else {
		info.querySelector(".views").classList.add("hidden");
		info.querySelector(".views-value").textContent = "";
	}
	
	// Original URL
	const link = info.querySelector(".link");
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
		// Round to 1 decimal place
		let inset = Math.round((100 - ((video.average_rating * 16) + 
					(Math.floor(video.average_rating) * 5))) * 10) / 10;
		inset = (inset <= 0 ? 0 : inset); // Avoid -5% inset on a perfect 5*
		info.querySelector(".stars-filled")
			.style.clipPath = "inset(0 " + inset + "% 0 0)";
		// Numeric rating rounded to 2 places
		const rating = Math.round(video.average_rating * 100) / 100;
		info.querySelector(".rating-value").textContent = rating;
		// Likes/dislikes as tooltip
		if (video.like_count !== null && video.dislike_count !== null) {
			info.querySelector(".rating").title = video.like_count +
				" likes, " + video.dislike_count + " dislikes";
		}
		info.querySelector(".rating").classList.remove("hidden");
	} else {
		// Default to empty stars & hide
		info.querySelector(".rating").classList.add("hidden");
		info.querySelector(".stars-filled")
			.style.clipPath = "inset(0 100% 0 0)";
		info.querySelector(".rating-value").textContent = "";
	}
	
	// Date (if uploaded missing, get downloaded from modtime)
	if (video.upload_date === null && video.modification_time !== null) {
		info.querySelector(".date-value")
			.textContent = video.modification_time;
		info.querySelector(".date-type").textContent = "Downloaded";
		info.querySelector(".date").classList.remove("hidden");
	} else {
		// Default label
		info.querySelector(".date-type").textContent = "Uploaded";
		// Date downloaded as tooltip
		info.querySelector(".date").title = "Downloaded " +
											video.modification_time;
	}
	
	// Resolution and/or fps (add suffixes and concat)
	const height = (video.height !== null ? video.height + "p" : null);
	const fps = (video.fps !== null
			  ? Math.round(video.fps * 100) / 100 + "fps" : null);
	// Empty string if both missing
	const format = [height, fps].filter(Boolean).join(" ");
	info.querySelector(".resolution-fps").textContent = format;
	if (format !== "") {
		// Show if at least one of resolution, format or codec are present
		info.querySelector(".format").classList.remove("hidden");
	}
	
	// Description (replace newlines with <br>)
	const description = descriptionContainer.querySelector(".description");
	if (video.description !== null) {
		description.innerText = video.description; // Insert safely
		description.classList.remove("hidden");
	} else {
		description.classList.add("hidden");
		description.innerText = "";
	}
	
	// Show info container
	infoContainer.classList.remove("hidden");
	
	// Test if description fits and fade if not
	// Allow to overflow
	infoContainer.classList.remove("full-height");
	// Test overflow: if yes, fade description and display "show more" link
	// 				  if no, remove fade and hide "show more" link
	descriptionOverflow();
	
	// Play video
	playVideo();
}

// Load a video with unknown playlist
async function loadVideoPrePlaylist(videoID, addHistory = false) {
	// Load video optionally adding to history, wait for playlist ID
	await loadVideo(videoID, addHistory);
	// Select playlist
	selectItem("playlist", current.video.folder_id);
	// Load playlist, select video
	loadPlaylist(current.video.folder_id);
}


// Load and display thumbnails from a Map of videoID: element
const thumbsPerRq = 10;
async function loadThumbs(thumbQueue) {
	const haveObserver = (typeof(observer.unobserve) === "function"
					   ? true : false);
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
			// Stop observing this element
			// (also prevents retry if no thumb returned)
			if (haveObserver) {
				observer.unobserve(element);
			}
		};
	}));
};

// Watch for changes in visible playlist items and trigger thumbnail loads
let observer = {};
function createObserver(rootElement) {
	const obs = new IntersectionObserver(intersectionChanged, {
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
		// Once no more thumbs queued for inputDelay, get thumbs
		// (with queue at time of calling, in case more added)
		intersectionTimer = setTimeout(thumbsFromPending, inputDelay);
	}
};


// Search metadata fields for videos
let prevQuery = searchInput.value;
function searchVideos(checkInputChanged = true) {
	const searchQuery = searchInput.value;
	if (!checkInputChanged || searchQuery !== prevQuery) {
		// Input changed
		prevQuery = searchQuery;
		if (searchQuery.length === 0) {
			// Input cleared, clear results
			displaySearch(null);
		} else if (searchQuery.length >= 3) {
			// Input over minimum length, do search
			loadSearch(searchField.value, searchQuery);
		}
	}
};			

let abortController = null;
async function loadSearch(field, query) {
	if (abortController) {
		// Cancel the previous request if pending
		abortController.abort();
		abortController = null;
	}
	
	abortController = new AbortController();
	try {
		const results = await loadJSON(abortController.signal,
									   "POST", query, "search", field);
		displaySearch(results.data);
	} catch(err) {
		// Request aborted or errored
	} finally {
		abortSearchController = null;
	}
};

// Display search results, or pass results = null to clear
function displaySearch(results) {
	// Create empty results list from container
	let newResultsList = searchResults.cloneNode(false);
	let thumbQueue = new Map();
	if (results) {
		// Show new results
		if (results.length > 0) {
			const template = document.getElementById("template-result");
			results.forEach((result) => {
				let resultElement = template.content.firstElementChild
											.cloneNode(true);
				// Populate template
				resultElement.setAttribute("data-video", result.id);
				resultElement.querySelector(".name").textContent = result.t;
				resultElement.querySelector(".folder").textContent = result.p;
				// Include formatting from escaped snippet
				resultElement.querySelector(".match").innerHTML = result.s;
				
				resultElement.addEventListener("click", async function() {
					// Search result clicked
					const id = this.getAttribute("data-video") << 0;
					// Hide results list
					searchResults.classList.add("hidden");
					// Load video and playlist, adding to history
					loadVideoPrePlaylist(id, true);
				});
				
				// Add result to list
				newElement = newResultsList.appendChild(resultElement);
				// Add thumbnail to queue
				thumbQueue.set(result.id, newElement.querySelector(".thumb"));
			});
		} else {
			// 0 results, insert placeholder
			let placeholder = document.createElement("div");
			placeholder.className = "placeholder";
			placeholder.textContent = "No results";
			newResultsList.appendChild(placeholder);
		}
	}
	
	// Replace existing results list, clearing listeners
	searchResults.parentNode.replaceChild(newResultsList, searchResults);
	searchResults = newResultsList;
	showResults();
	
	if (getThumbs && thumbQueue.size > 0) {
		// Trigger thumbnail load
		loadThumbs(thumbQueue);
	}
};

// Show results container
function showResults() {
	searchResults.classList.remove("hidden");
	// Click outside search hides
	document.addEventListener("click", function hideResults(event) {
		if (event.target.closest("#search") === null) {
			searchResults.classList.add("hidden");
			document.removeEventListener("click", hideResults);
		}
	});
};

// Play the currently-loaded video
const playManual = playerContainer.querySelector(".play-manual");
function playVideo() {
	// Hide manual play button if present
	playManual.classList.add("hidden");
	// Play video
	player.play()
	.then(() => {
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
			updatePositionState();
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
			return element.getAttribute(attribute) << 0;
		}
	}
}


// Show "show more" if description overflows container
const showMore = infoContainer.querySelector(".show-more");
function descriptionOverflow() {
	if (!infoContainer.classList.contains("full-height")) {
		// Container height is limited, test overflow
		if (info.offsetHeight + 1 < info.scrollHeight) {
			// Description overflows, fade and show button
			showMore.classList.remove("hidden");
		} else {
			// Description fits, show in full and hide button
			infoContainer.classList.add("full-height");
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


/**
Set up media notification controls
*/
function updatePositionState() {
	if ("setPositionState" in navigator.mediaSession) {
		// Set duration
		navigator.mediaSession.setPositionState({
			duration: player.duration,
			playbackRate: player.playbackRate,
			position: player.currentTime
		});
	}
}

if ("mediaSession" in navigator) {
	// Set up notification buttons
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
		updatePositionState();
	});
	navigator.mediaSession.setActionHandler("seekbackward", function(event) {
		const skipTime = event.seekOffset || defaultSkipTime;
		// Min skip to start of video
		player.currentTime = Math.max(player.currentTime - skipTime, 0);
		updatePositionState();
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