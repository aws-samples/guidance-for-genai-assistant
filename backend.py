import boto3
import json
import time
import re
import os
import requests
import env
from youtube_transcript_api import YouTubeTranscriptApi
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from contextlib import closing
import streamlit as st
from langchain.prompts import PromptTemplate
from langchain.chains import ConversationChain
from langchain_community.chat_models import BedrockChat
from langchain.memory import ConversationBufferMemory

region = env.region
s3_bucket = env.s3_bucket_name
session = boto3.Session(region_name=region)

def create_beddrock_client():
        bedrock_client = session.client("bedrock-runtime")
        return bedrock_client

transcribe_client = session.client("transcribe")



def start_transcription_job(job_name,media_file):
    try:
        with st.spinner('Generating transcription for uploaded media file...'):
            s3_url = 's3://'+s3_bucket+'/'+media_file.name
            response = transcribe_client.start_transcription_job(
                TranscriptionJobName=job_name,
                Media={'MediaFileUri': s3_url},
                MediaFormat=os.path.splitext(s3_url)[1][1:],  # Extract file extension
                LanguageCode='en-US'
            )
            return response
    except Exception as e:
        st.error(e)
        return 'err'

def get_transcription_job_status(job_name):
    while True:
        status = transcribe_client.get_transcription_job(TranscriptionJobName=job_name)
        job_status = status['TranscriptionJob']['TranscriptionJobStatus']
        if job_status in ['COMPLETED', 'FAILED']:
            return status
        print(f"Waiting for job {job_name} to complete...")
        time.sleep(3)


def transcribe_media(media_file):

    try:
        with st.spinner('Generating transcription for uploaded media file...'):
        # Generate a unique job name
            job_name = f"transcription_job_{int(time.time())}"
    
    
    # Start the transcription job
    #print(f"Starting transcription job: {job_name}")
            job_details=start_transcription_job(job_name, media_file)
    # Wait for the transcription job to complete
            status = get_transcription_job_status(job_name)
        if status['TranscriptionJob']['TranscriptionJobStatus'] == 'COMPLETED':
        # Download and return the transcript
            with st.spinner('Fetching Transcription...'):
                response = requests.get(status['TranscriptionJob']['Transcript']['TranscriptFileUri']).text
                data =json.loads(response)
                transcript = data['results']['transcripts'][0]['transcript']
                print("Transcription complete.")
                return transcript 
        else:
            raise Exception(f"Transcription job failed: {status}")
    except Exception as e:
        st.error(e)
        return 'err'



def create_polly_client():
    polly = session.client('polly')
    return polly

def create_textract_client():
    textract = session.client('textract')
    return textract

def create_s3_client():
    s3_client = session.client('s3')
    return s3_client

if s3_bucket == '':
    st.error('Could not find Amazon S3 bucket name. Please update the Amazon S3 bucket name in env.py file and try again.')
    st.stop()


def upload_to_s3(file):
    try:
        with st.spinner('Uploading file to S3...'):
            s3_client = create_s3_client()
            response_s3 = s3_client.upload_fileobj(file, s3_bucket,file.name )
            return response_s3 
    except:
        return 'err'

def get_s3_pdf(file):
    try:
        with st.spinner('Extracting text from uploaded file...'):
            result_pdf = pdf_text(s3_bucket,file.name)
            return result_pdf
    except:
        return 'err_extract'




def pdf_text(s3_bucket,s3_file):
    try:
        textract = create_textract_client()
        result = textract.start_document_text_detection(
                DocumentLocation={
                    'S3Object': {
                    'Bucket': s3_bucket,
                    'Name': s3_file
                    }})
        job_id = result['JobId']

        if is_job_complete(textract, job_id):
            response_job = get_job_results(textract, job_id)

        if response_job:
            doc =''
            for result_page in response_job:
                for item in result_page["Blocks"]:
                    if item["BlockType"] == "LINE":
                        doc += item["Text"] +'\n'

        return doc 
    except Exception as e:
        return e


def is_job_complete(client, job_id):
    time.sleep(3)
    response = client.get_document_text_detection(JobId=job_id)
    status = response["JobStatus"]
    print("Job status: {}".format(status))

    while(status == "IN_PROGRESS"):
        time.sleep(3)
        response = client.get_document_text_detection(JobId=job_id)
        status = response["JobStatus"]
        print("Job status: {}".format(status))

    return status


def get_job_results(client, job_id):
    pages = []
    time.sleep(1)
    response = client.get_document_text_detection(JobId=job_id)
    pages.append(response)
    print("Resultset page received: {}".format(len(pages)))
    next_token = None
    if 'NextToken' in response:
        next_token = response['NextToken']

    while next_token:
        time.sleep(1)
        response = client.\
            get_document_text_detection(JobId=job_id, NextToken=next_token)
        pages.append(response)
        print("Resultset page received: {}".format(len(pages)))
        next_token = None
        if 'NextToken' in response:
            next_token = response['NextToken']

    return pages


def create_speech(input_text):
    output_format = "mp3"
    voice_id = "Matthew"
    polly = create_polly_client()
    response = polly.synthesize_speech(
            Text=input_text,
            OutputFormat=output_format,
            VoiceId=voice_id
            )
    file_name='genai_assistant.mp3'
    if "AudioStream" in response:
            with closing(response["AudioStream"]) as stream:
                output = os.path.join(os.getcwd(), file_name)
                try:
                    with open(output, "wb") as file:
                        file.write(stream.read())
                        return (file_name)
                except IOError as error:
                    print(f"Error: {error}")
    else:
        print("None")



def aws_llm_chain():
    try:
        model_id = "anthropic.claude-3-sonnet-20240229-v1:0"
        model_kwargs =  {
            "max_tokens": 500, #Max output tokens generated by model. 4096 token ~3.1K words.
            "temperature": 1, #Amount of randomness in response.
            "stop_sequences": ["\n\nHuman"],
        }
        model = BedrockChat(
            client=create_beddrock_client(),
            model_id=model_id,
            model_kwargs=model_kwargs,
        )

        prompt_template = """System: I want you to provide brief summary of this input provided, and then list the key points or key takeaways. Add conclusion at the end.

        Current conversation:
        {history}

        User: {input} 
        Assistant:"""
  
        prompt = PromptTemplate(
            input_variables=["history", "input"], template=prompt_template
        ) 

        memory = ConversationBufferMemory(human_prefix="User", ai_prefix="Assistant",max_length=5)
        conversation = ConversationChain(
            prompt=prompt,
            llm=model,
            verbose=True,
            memory=memory,
        )
        return conversation

    except Exception as e:
        st.error('aws_llm_chain_exception')
        st.error(e)
        return 'Error'

def chat_bot():
    try:
        model_id = "anthropic.claude-3-sonnet-20240229-v1:0"
        model_kwargs =  {
            "max_tokens": 500, #Max output tokens generated by model. 4096 token ~3.1K words.
            "temperature": 1, #Amount of randomness in response.
            "stop_sequences": ["\n\nHuman"],
        }
        model = BedrockChat(
            client=create_beddrock_client(),
            model_id=model_id,
            model_kwargs=model_kwargs,
        )
    
        prompt_template = """System: You are a chatbot that help user in answering their question.
        Current conversation:
        {history}
        User: {input}
        Assistant:"""

        prompt = PromptTemplate(
            input_variables=["history", "input"], template=prompt_template
        )

        memory = ConversationBufferMemory(human_prefix="User", ai_prefix="Assistant",max_length=5)
        conversation = ConversationChain(
            prompt=prompt,
            llm=model,
            verbose=True,
            memory=memory,
        )
        return conversation

    except Exception as e:
        st.error('Chatbot Exception Occur')
        st.error(e)
        return 'Error'



def prepare_chain(chain,transcript):
    summary= chain.invoke({'input':transcript})
    return summary['response']

def fetch_blogs(url):
    try:
        # Send a GET request to the specified URL
        response = requests.get(url)
        if response.status_code != 200:
            return 403,'error'

        # Parse the HTML content of the page with BeautifulSoup
        soup = BeautifulSoup(response.content, 'html.parser')

        # Extract all text content from the page
        transcript = soup.get_text(separator='\n')
        title_tag = soup.find('meta', property='og:title')
        b_title = title_tag['content'] if title_tag else 'None'
        return transcript.strip(),b_title

    except:
        return 'error','None' 


def get_video_id(url):
    # Extract the video ID from the YouTube URL
    video_id = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11}).*', url)
    return video_id.group(1) if video_id else None

def fetch_youtube_transcript(video_id):
    try:
        # Fetch the transcript using youtube-transcript-api
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        # Combine the text from the transcript entries
        transcript = ' '.join([entry['text'] for entry in transcript_list])
        return transcript
    
    except Exception as e:
        return 'None' 

def get_y_title(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.text, features='html.parser')
    link = soup.find_all(name="title")[0]
    title = str(link)
    title = title.replace("<title>","")
    title = title.replace("</title>","")
    title = title.replace("- YouTube","")
    return title

def check_url(url):
    url_domain=urlparse(url).netloc
    if url_domain == 'www.youtube.com':
        return 'true'
    elif url_domain.strip() == '':
        return 'error'
    else:
        return 'false'


def generate_summary(url,llm_chain):
    url_domain=urlparse(url).netloc
    if url_domain == 'www.youtube.com':
        video_id = get_video_id(url)
        if video_id:
            transcript = fetch_youtube_transcript(video_id)
            summary = prepare_chain(llm_chain,transcript)
            y_title = get_y_title(url)
            return summary,video_id,y_title
        else:
            return "Invalid YouTube URL."
    else:
        transcript,b_title = fetch_blogs(url)
        if transcript == 403:
            return 403,'403','403' 
        summary = prepare_chain(llm_chain,transcript)
        return summary,'no_video',b_title



