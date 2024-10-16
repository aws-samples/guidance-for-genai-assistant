import backend 
import streamlit as st

st.set_page_config(
        page_title="GenAI Assistant",page_icon='🧊'
)
st.title(":blue[GenAI Assistant:] _Summarize and Chat with Blogs, pdfs or media files_")


def clear_input():
    for key in st.session_state.keys():
        del st.session_state[key]

if "llm_chain" not in st.session_state:
    st.session_state["llm_chain"] = backend.aws_llm_chain()

if "messages" not in st.session_state:
    st.session_state["messages"] = []

st.sidebar.subheader('Choose your options here')
page=st.sidebar.radio("Choose Input options",["URL", "PDF", "Media","ChatBot"],captions=["Ener Web URL link","Upload pdf document","Upload media (mp3|mp4)","Chat with Assistant"],label_visibility="collapsed",index=3,on_change=clear_input)

def create_session_key(key,val):
    st.session_state[key]=val


def clear_msgs():
    if "messages" in st.session_state:
        st.session_state.messages=[]

def url_submit():
    if 'user_input' in st.session_state and st.session_state.user_input.strip() !='':
        st.session_state.input_url = st.session_state.user_input
        st.session_state.user_input = ""
    clear_msgs()    

def clear_input():
    if "input_url" in st.session_state:
        del st.session_state.input_url 

def process_input():
    is_yt_url = backend.check_url(st.session_state.input_url)
    if is_yt_url == 'error':
        st.error('Invalid URL!')
        st.stop()
    create_session_key('is_yt_url',is_yt_url)
    if is_yt_url == 'true':
        video_id = backend.get_video_id(st.session_state.input_url)
        create_session_key('video_id',video_id)
        if video_id:
            url_title = backend.get_y_title(st.session_state.input_url)
            transcript = backend.fetch_youtube_transcript(video_id)
            with st.spinner("Generating Summary..."):
                url_summary = backend.prepare_chain(st.session_state.llm_chain,transcript)
        else:
            st.error('Youtube video does not have any english transcript!')
            st.stop()

    else:
            transcript,url_title = backend.fetch_blogs(st.session_state.input_url)
            with st.spinner("Generating Summary..."):
                url_summary = backend.prepare_chain(st.session_state.llm_chain,transcript)
    create_session_key('url_title',url_title)
    create_session_key('url_summary',url_summary)

    #clear input session key to avoid reload during chat
    clear_input()

def generate_audio(summary):
    audio_file = backend.create_speech(summary)
    if audio_file !='None':
        st.audio(audio_file, format="audio/mpeg")

def process_msg(prompt):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.spinner("One moment..."):
        q_ans = backend.prepare_chain(st.session_state.llm_chain,prompt)
    st.session_state.messages.append({"role": "assistant", "content": q_ans})

def setup_page():
    if "is_yt_url" in st.session_state:
        #check if valid url title has returned
        if st.session_state.url_title !='None':
            st.subheader(st.session_state.url_title)
        #Check if input url belongs to youtube video
        if st.session_state.is_yt_url == 'true':
            st.image('https://img.youtube.com/vi/'+st.session_state.video_id+'/0.jpg')
        st.info(st.session_state.url_summary)

        #Generating audio response
        generate_audio(st.session_state.url_summary)

def setup_msgs():
    if "messages" in st.session_state:
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

def process_file(upload_file,type):
    try:
        result_s3 = backend.upload_to_s3(upload_file)
    except Exception as e:
        st.error('Unable to upload file to S3')
        st.stop()

    if result_s3 !='err':
        try:
            if type =='pdf':
                response_extract = backend.get_s3_pdf(upload_file)
            elif type =='media':
                response_extract = backend.transcribe_media(upload_file)
        except Exception as e:
            st.error('Error during file processing!')
            #st.error(e)
            st.stop()
        try:
            with st.spinner('Generating Summary...'):
               response = backend.prepare_chain(st.session_state.llm_chain,response_extract)
            st.session_state.file_response= response
        except Exception as e:
            st.error('Error occur while generating summary!')
            #st.error(e)
            st.stop()
    else:
        st.write('Unable to process the file. Plese verify Amazon S3 bucket name and/or file uploaded is correct. Refresh the page before retry.')
        st.stop()



####### Input Option #1 ###############

if page == "URL":
    st.text_input(":Gray[Enter URL of a blog post or YouTube video to generate summary ]",placeholder="https://www.aboutamazon.com/news/aws/generative-ai-is-the-future", key="user_input", on_change=url_submit)

    if 'input_url' in st.session_state:
        process_input()
    setup_page()
    #Chat option enabled only when a URL summary is recorded
    if 'url_summary' in st.session_state:
        prompt_msg = st.chat_input("Ask me for more details!")
        if prompt_msg:
            process_msg(prompt_msg)

        setup_msgs()


####### Input Option #2 ###############
elif page == "PDF":
    upload_file = st.file_uploader("Upload pdf files [1 MB Max] to generate summary!", type="pdf")

    if upload_file and 'file_response' not in st.session_state:
        process_file(upload_file,'pdf') 
        # Removing old chat messages
        clear_msgs()

    if 'file_response' in st.session_state:
        st.info(st.session_state.file_response)
        #Generating audio response
        generate_audio(st.session_state.file_response)
        prompt_msg = st.chat_input("Ask me for more details!")
        if prompt_msg:
            process_msg(prompt_msg)

        setup_msgs()



####### Input Option #3 ###############
elif page == "Media":
    upload_media = st.file_uploader("Upload media files to generate summary!", type=['mp3','mp4','wav','flac','ogg','amr','webm','m4a'])

    if upload_media and 'file_response' not in st.session_state:
        process_file(upload_media,'media')
        # Removing old chat messages
        clear_msgs()

    if 'file_response' in st.session_state:
        st.info(st.session_state.file_response)
        #Generating audio response
        generate_audio(st.session_state.file_response)
        prompt_msg = st.chat_input("Ask me for more details!")
        if prompt_msg:
            process_msg(prompt_msg)

        setup_msgs()



####### Input Option #4 ###############
elif page == "ChatBot":
    st.subheader('GenAI Chat Assistance')
    if 'chatbot' not in st.session_state:
        st.session_state.chatbot ='chat'
        st.session_state.llm_chain = backend.chat_bot()
        process_msg('Hello')
    prompt_msg = st.chat_input("Ask me anything!")
    if prompt_msg:
        process_msg(prompt_msg)

    setup_msgs()


