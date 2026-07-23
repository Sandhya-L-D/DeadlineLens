import streamlit as st

@st.cache_data(ttl=300)
def get_cached_deadlines(loader):
    return loader()


@st.cache_data(ttl=300)
def get_cached_dashboard(loader):
    return loader()


@st.cache_data(ttl=300)
def get_cached_calendar(loader):
    return loader()


def clear_all_cache():
    st.cache_data.clear()