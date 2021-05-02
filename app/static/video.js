// Get player
const playerContainer = document.getElementById("player");
const player = playerContainer.querySelector("video");
// Get infobox
const infoContainer = document.getElementById("info");
const info = infoContainer.querySelector(".info");

document.addEventListener("DOMContentLoaded", (event) => {
	// Load video ID from query params if present
	async function loadVideoFromURL(videoID) {
		var playlistID = await loadVideo(videoID);
		
		// Unmark previously selected playlist and video (if any)
		var listElements = ["playlists", "videos"]
		listElements.forEach(function(element) {
			var selected = document.getElementById(element).querySelector(".selected");
			if (selected !== null) {
				selected.classList.remove("selected");
			};
		});
		
		// Mark current playlist selected
		// todo: combine this with loadPlaylist (same below) (+ for video)
		document.getElementById("playlists").querySelector("[data-playlist='" + playlistID + "']").classList.add("selected");
		// Load playlist
		await loadPlaylist(playlistID);
		// Mark current video selected and scroll into view
		var videoListing = document.getElementById("videos").querySelector("[data-video='" + videoID + "']")
		videoListing.classList.add("selected");
		videoListing.scrollIntoView();
	};
	if (video_id !== null) {
		loadVideoFromURL(video_id)
	};
	
	// Listen for playlist clicks
	document.getElementById("playlists").querySelectorAll(".playlist").forEach(function(element) {
		element.addEventListener("click", () => {
			// Unmark previously selected
			var selected = document.getElementById("playlists").querySelector(".selected");
			if (selected !== null) {
				selected.classList.remove("selected");
			};
			// Mark selected
			element.classList.add("selected");
			// Load playlist
			loadPlaylist(element.getAttribute("data-playlist"));
		});
	});
	
	// Listen for manual play button clicks
	playerContainer.querySelector(".play-manual").addEventListener("click", () => {
		// Hide play button
		playerContainer.querySelector(".play-manual").classList.add("hidden");
		// Play video
		player.play();
	});
	
	// Listen for "show more" clicks
	var showLinks = infoContainer.querySelectorAll(".show-more-less a");
	showLinks.forEach(function(element) {
		element.addEventListener("click", () => {
			// Toggle full-height description
			info.querySelector(".description-container").classList.toggle("full-height");
			// Toggle show more/less
			showLinks.forEach(function(element) {
				element.classList.toggle("hidden");
			});
		});
	});
		// if (document.querySelector(".description-container").classList.contains("full-height")) {
			// document.querySelector(".more-link").innerHTML = "Show less";
		// } else {
			// document.querySelector(".more-link").innerHTML = "Show more";
		// };
});

async function loadPlaylist(playlistID) {
	var playlist = await loadJSON("playlist/" + playlistID);
	displayPlaylist(playlist.data);
};

function displayPlaylist(playlist) {
	// Current playlist
	var videoList = document.getElementById('videos');
	// Empty playlist
	var newVideoList = videoList.cloneNode(false);
	
	// Add each video to list
	// todo: add sort function https://stackoverflow.com/questions/881510/sorting-json-by-values or https://medium.com/@asadise/sorting-a-json-array-according-one-property-in-javascript-18b1d22cd9e9
	playlist.forEach(function(video) {
		var videoElement = document.createElement("li");
		videoElement.className = "video";
		videoElement.setAttribute("data-video", video.id);
		
		var thumbElement = document.createElement("div");
		thumbElement.className = "thumbnail";
		
		if (video.duration != null) {
			var durationElement = document.createElement("div");
			durationElement.className = "duration";
			durationElement.innerHTML = video.duration;
			thumbElement.appendChild(durationElement);
		};
		
		if (video.thumbnail != null) {
			// Add thumbnail if present
			var thumbImgElement = document.createElement("img");
			thumbImgElement.src = video.thumbnail;
			thumbElement.appendChild(thumbImgElement);
		} else {
			// Add position if not
			thumbElement.classList.add("count");
			var thumbPositionElement = document.createElement("div");
			thumbPositionElement.className = "number";
			// todo: make this the attribute sorted by
			thumbPositionElement.innerHTML = video.id;
			thumbElement.appendChild(thumbPositionElement);
		};
		videoElement.appendChild(thumbElement);
		
		// Add title
		var nameElement = document.createElement("div");
		nameElement.className = "name";
		nameElement.innerHTML = video.title;
		videoElement.appendChild(nameElement);
		
		newVideoList.appendChild(videoElement);
	});
	
	// Replace existing playlist with new
	videoList.parentNode.replaceChild(newVideoList, videoList);
	
	// Add listeners for video being clicked
	document.getElementById("videos").querySelectorAll(".video").forEach(function(element) {
		element.addEventListener("click", () => {
			// Unmark previously selected
			var selected = document.getElementById("videos").querySelector(".selected");
			if (selected !== null) {
				selected.classList.remove("selected");
			};
			// Mark selected
			element.classList.add("selected");
			// Load video
			loadVideo(element.getAttribute("data-video"));
		});
	});
};

async function loadVideo(videoID) {
	var video = await loadJSON("video/" + videoID);
	// Update page URL to allow linking to video
	window.history.pushState({}, "", "/v/" + videoID);
	displayVideo(video.data);
	// Return folder ID so can select current playlist on load from URL
	return video.data.folder_id;
};

function displayVideo(video) {
	// Pause current video
	player.pause();
	// Remove existing source
	var source = player.getElementsByTagName("source")[0];
	player.removeChild(source)
	// Create new source
	var newSource = document.createElement("source");
	newSource.src = video.path;
	newSource.type = video.video_format;
	player.appendChild(newSource);
	// Load video
	player.load();
	
	// Hide info box until ready
	infoContainer.classList.add("hidden");
	
	// Add metadata
	// Normal fields (metadata can be inserted directly):
	//   key: json field
	//   display: selector to hide if data missing
	//   contents: selector to fill with data (if different from display)
	var metadataFields = {
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
	
	Object.entries(metadataFields).forEach(function([key, field]) {
		var contentField = (field.contents !== undefined ? field.contents : field.display);
		if (video[key] !== null) {
			// todo: rest of display: etc like this vv
			
			// Field has data, fill and show
			//var fieldData = video[key];
			//var displayStyle = "block";
			info.querySelector(contentField).innerHTML = video[key];
			info.querySelector(field.display).classList.remove("hidden");
		} else {
			// No data for field, hide and empty
			//var displayStyle = "none";
			//var fieldData = "";
			info.querySelector(contentField).innerHTML = "";
			info.querySelector(field.display).classList.add("hidden");
		};
		// if (field.contents !== undefined) {
			// info.querySelector(field.contents).innerHTML = fieldData;
		// } else {
			// info.querySelector(field.display).innerHTML = fieldData;
		// };
		// info.querySelector(field.display).style.display = displayStyle;
	});
	
	// Special case fields
	// Uploader link (still hidden if no uploader name)
	if (video.uploader_url !== null) {
		info.querySelector(".uploader").href = video.uploader_url;
	};
	
	// Views (add separators)
	if (video.view_count !== null) {
		info.querySelector(".views-value").innerHTML = Number(video.view_count).toLocaleString();
		info.querySelector(".views").classList.remove("hidden");
	} else {
		info.querySelector(".views").classList.add("hidden");
		info.querySelector(".views-value").innerHTML = "";
	};
	
	// Original URL
	var linkElement = info.querySelector(".link");
	if (video.video_url !== null) {
		linkElement.href = video.video_url;
		linkElement.classList.remove("hidden");
	} else {
		linkElement.classList.add("hidden");
		linkElement.href = "";
	};
	
	/**
	   Star rating
	   Stars in image have defined widths and gaps, so we can calculate the
	   inset to apply to ignore gaps and only clip stars:
	   
		0% 16 21 37 42 58 63 79 84 100%
		|   | |   | |   | |   | |   |
	
	   e.g. 1.5 stars is 29% (71% inset)
	*/
	if (video.average_rating !== null) {
		var inset = Math.round(100 - ((video.average_rating * 16) + (Math.floor(video.average_rating) * 5)) * 100) / 100; // * 100, round, / 100 gives 2 decimal places
		if (video.average_rating == 5) {
			// Avoid -5% inset on a perfect 5*
			var inset = 0;
		}
		info.querySelector(".stars-filled").style.clipPath = "inset(0 " + inset + "% 0 0)";
		// Number too
		var rating = Math.round(video.average_rating * 100) / 100;
		info.querySelector(".rating-value").innerHTML = rating;
		info.querySelector(".rating").classList.remove("hidden"); // Grid for overlaying images
	} else {
		// Default to empty stars & hide
		info.querySelector(".rating").classList.add("hidden");
		info.querySelector(".stars-filled").style.clipPath = "inset(0 100% 0 0)";
		info.querySelector(".rating-value").innerHTML = "";
	};
	
	// Date (if uploaded missing, get downloaded from modtime)
	if (video.upload_date == null && video.modification_time !== null) {
		info.querySelector(".date-value").innerHTML = video.modification_time;
		info.querySelector(".date-type").innerHTML = "Downloaded";
		info.querySelector(".date").classList.remove("hidden");
	} else {
		// Default label
		info.querySelector(".date-type").innerHTML = "Uploaded";
	};
	
	// Resolution and/or fps (add suffixes and concat)
	var height = (video.height !== null ? video.height + "p" : null);
	var fps = (video.fps !== null ? Math.round(video.fps * 100) / 100 + "fps" : null);
	var format = [height, fps].filter(Boolean).join(" ");
	info.querySelector(".resolution-fps").innerHTML = format; // Empty if both missing
	if (format !== "") {
		// Show if at least one of resolution, format or codec are present
		info.querySelector(".format").classList.remove("hidden");
	};
	
	// Description (replace line breaks with HTML)
	var descriptionElement = info.querySelector(".description");
	if (video.description !== null) {
		// Replace newlines with HTML breaks
		var description = video.description.replace(/\n/g, "<br>\n");
		// Replace double breaks with paragraphs
		description = description.replace(/<br>\n<br>\n/g, "</p>\n<p>");
		// Wrap everything in a paragraph
		description = "<p>" + description + "</p>";
		descriptionElement.innerHTML = description;
		descriptionElement.classList.remove("hidden");
	} else {
		descriptionElement.classList.add("hidden");
		descriptionElement.innerHTML = "";
	};
	
	// Categories and tags
	//   key: json array field
	//   display: list of selectors to hide if data missing
	//   contents: selector to fill with data
	var listFields = {
		categories: {
			display: [".categories-label", ".categories"],
			contents: ".categories" },
		tags: {
			display: [".tags-label", ".tags"],
			contents: ".tags" }
	};
	
	Object.entries(listFields).forEach(function([key, field]) {
		// Default empty and hide
		var fieldData = "";
		var fieldHidden = true;
		if (Array.isArray(video[key]) && video[key].length !== 0) {
			// List has items
			// Remove invalid/empty items, comma-separate and show
			var fieldData = video[key].filter(Boolean).join(", ");
			var fieldHidden = false;
		};
		
		info.querySelector(field.contents).innerHTML = fieldData;
		field.display.forEach(function(element) {
			if (fieldHidden) {
				info.querySelector(element).classList.add("hidden");
			} else {
				info.querySelector(element).classList.remove("hidden");
			};
		});
	});
	
	// Reset "show more"
	var descriptionContainer = infoContainer.querySelector(".description-container");
	descriptionContainer.classList.remove("full-height");
	infoContainer.querySelector(".more-link").classList.remove("hidden");
	infoContainer.querySelector(".less-link").classList.add("hidden");
	
	// Show info container
	infoContainer.classList.remove("hidden");
	
	// If description overflows, show "show more" link
	if (descriptionContainer.offsetHeight < descriptionContainer.scrollHeight) {
		infoContainer.querySelector(".show-more-less").classList.remove("hidden");
	} else {
		infoContainer.querySelector(".show-more-less").classList.add("hidden");
	};
	
	// Hide play button if present
	playerContainer.querySelector(".play-manual").classList.add("hidden");
	// Remove placeholder if present
	player.poster = "";
	// Play video
	var playPromise = player.play();
	
	playPromise.then(function() {
		// Playback started
	}).catch(function(error) {
		// Playback failed (probably user hasn't interacted with page)
		// Set thumbnail as placeholder
		if (video.thumbnail !== null) {
			player.poster = video.thumbnail;
		};
		// Show manual play button
		playerContainer.querySelector(".play-manual").classList.remove("hidden");
	});
};