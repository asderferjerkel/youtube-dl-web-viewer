document.addEventListener("DOMContentLoaded", (event) => {
	// Playlist is clicked
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
			loadJSON("playlist/" + element.getAttribute("data-playlist"), displayPlaylist);
		});
	});
});

function displayPlaylist() {
	// Clear existing videos
	var videoList = document.getElementById('videos');
	var emptyVideoList = videoList.cloneNode(false);
	videoList.parentNode.replaceChild(emptyVideoList, videoList);
	
	// Add each video to list
	// todo: add sort function https://stackoverflow.com/questions/881510/sorting-json-by-values or https://medium.com/@asadise/sorting-a-json-array-according-one-property-in-javascript-18b1d22cd9e9
	this.data.forEach(function(video) {
		var videoElement = document.createElement("li");
		videoElement.classList = "video";
		videoElement.setAttribute("data-video", video.id);
		
		var thumbElement = document.createElement("div");
		thumbElement.className = "thumbnail";
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
		
		emptyVideoList.appendChild(videoElement);
	});
	
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
			loadJSON("video/" + element.getAttribute("data-video"), displayVideo);
		});
	});
};

function displayVideo() {
	// Set player src
	videoPlayer = document.getElementById("player").querySelector("video");
	videoPlayer.querySelector("source").src = this.data.path;
	videoPlayer.querySelector("source").type = this.data.video_format;
	
	if (this.data.thumbnail !== null) {
		videoPlayer.poster = this.data.thumbnail;
	};
	// Add info
	
	videoPlayer.play;
};