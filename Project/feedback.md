> **Archived grading feedback.** This is the professor's original grading
> rubric from before the project was renamed from "CueMix" to Cuemix; it does
> not describe the current architecture or feature set. Kept for reference
> only. See [README.md](README.md) for current behavior.

Noam  is NI and can make mistakes. 2026-06-24 17:46

# Project Guidelines: CueMix

**Course:** Software Engineering for ML (Spring 2026)  

**Authors:** Bayan Hathot, Mohammed Mrisat, Mahdi

**Date:** June 2026  

---

## Overview & Feedback

I love the idea! did you ever write audio processing code? if not, prepare for some surprises.

Main features: "user auth" is not main feature. Just somehing boring that has to be done.

how will user upload audio files? this can be a big challenge - if users likes your system or thrash it.

You plan a lot of GUI. hard to do locally, harder on a server.

How do the user selects segments? how mark them (no need to answer here -- just think of it and see if it is complicated).

You will have to explain "intelligent mixing"

Not clear to me if you plan to use (remote or local) AI. see below.

Think what features you can add that will benefit from AI (local or remote).

I will suggest a few more features to make this project well-rounded and complete using what you learned this semester. 

Hopefully, these features make sense with the vision you had for the project; if they don’t, feel free to change to another similar feature that will test the same concepts. 

> ⚠️ **Important:** Let me know via mail if you want to change these guidelines. 


### Grading & Submission Policy
* **Target Score (100 pts):** These guidelines represent the requirements needed to achieve a perfect score. You do not have to complete them all, and we do not expect you to. 
* **Partial Credit:** You will get partial credit for a partial completion of each feature.
* **Penalties:**
  * Each bug found: **-5 points**
  * Each week of delay in submission: **-5 points**

---

## Technical & Feature Guidelines

### 1. Project Proposal (50 Points)
Implement a working, localhost web application that implements your proposed idea. 
It should include everything mentioned in your proposal. Really intersted in seeing all the analytics dashboards and different modes (workout/relaxation...)

### 2. Long-Term Memory (5 Points)
Each user should have a dedicated record tracking their preferences/goals/ -- according to your specific project. 

### 3. Robustness to Hallucinations (10 Points) -- if you use AI model --
Ensure robustness against hallucinations. The AI must not recommend a non-existent item (for example, choosing a part of a song that is silence)

### 4. Job Queue (5 points):
people should be able to upload many songs at once, to make this a reality, and to make sure the files uploaded are actual songs. you will need to implement a Job Queue to be able to upload full playlists in parallel. Implement a smart Job Queue that utilizes parallel programming and smart priorities to deal with huge uploads of songs.

### 5. Local LLM Integration (10 Points)
Due to the high volume of API calls, relying on free external APIs (which suffer from low token limits or high hallucination rates) or expensive paid tiers is unviable.

You must download and run a **local open-source LLM** to handle complex conversations and extensive context data.

* **Performance:** The chosen model must be capable of tracking complex mathematical logic without losing context.
* **Concurrency:** You must implement parallel programming techniques (e.g. a queue to threads) to handle multi-user traffic smoothly without bottlenecking the server.

### 6. Online Forum & Communication Suite (10 Points)
Implement an integrated online forum resembling a social network or microblogging platform where users can share ideas, achievements, academic tips, and app feedback.

#### Core Forum Features:
1. **Public Posting:** Clients can create posts visible to everyone. Posts must support a title, body, images, and video attachments.
2. **Anonymity:** Users must have an explicit toggle to post anonymously.
3. **Commenting System:** Users can comment on any post with support for text, images, and videos.
4. **Engagements & Metrics:** Implement Upvote/Downvote functionality for posts and comments. Users must have a profile dashboard to track their total received engagement metrics.
5. **Direct Messaging (DM):** A private, secure peer-to-peer messaging feature supporting text, images, and video attachments.
6. **Live Notifications:** Real-time push notifications inside the web app for new DMs and upvote/downvote interactions.
7. **Security & Rate Limiting:** You must architect defenses against spamming (e.g., api rate-limiting to prevent a single user from sending 1,000 messages rapidly) and storage abuse (e.g., file-size restrictions on video uploads).
8. **Cold Seeding:** The application must launch with pre-seeded data consisting of simulated "fake" client accounts, historical posts, and active comment threads to populate the UI.

> 💡 **Technical Note:** All forum feeds, chat history retrievals, and notification delivery must operate in real-time without requiring manual page refreshes.

### 7. Website Deployment & CI/CD (10 Points)
* **Website Deployment:** Deploy your website to an azure cloud server (we will supply you with a server and a domain if you choose to do implement this feature, but you have to implement the deployment yourself). The website should be accessible to the public and be able to scale easily (use parallelization in your code).
* **CI/CD Pipeline:** Implement a CI/CD pipeline for your project’s private GitHub repository - the pipeline should include a test set that will run on each commit and check that all the tests pass - if they do, the pipeline should automatically deploy the new version of the website to the server. Only implementing the CI/CD pipeline without website deployment (only checking that the tests pass on each commit) will award you partial credit of 5 points.
