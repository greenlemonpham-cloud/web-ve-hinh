import streamlit as st

# Set up the page title and icon to look totally legit
st.set_page_config(
    page_title="Important Announcement",
    page_icon="🎁",
    layout="centered"
)

# Header trickery
st.title("🎉 You've unlocked secret access!")
st.subheader("Loading your content...")

# Trigger some celebration balloons
st.balloons()

# The Rickroll Video (Autoplay enabled)
# YouTube Embed URL for "Never Gonna Give You Up"
rickroll_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ&start_radio=1"

# Embedding via HTML iframe ensures autoplay works smoothly
st.components.v1.html(
    f"""
    <iframe 
        width="100%" 
        height="450" 
        src="{rickroll_url}" 
        title="Rick Astley - Never Gonna Give You Up" 
        frameborder="0" 
        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
        allowfullscreen>
    </iframe>
    """,
    height=470,
)

st.caption("You know the rules, and so do I. 😉")
