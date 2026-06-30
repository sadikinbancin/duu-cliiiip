import gradio as gr

def hello(video):
    if video is None:
        return "Upload video dulu Wee 🗿"
    return f"Video masuk: {video}"

demo = gr.Interface(
    fn=hello,
    inputs=gr.Video(label="Upload video"),
    outputs=gr.Textbox(label="Status"),
    title="Clipping Lite",
    description="AI auto clipper lite - test app"
)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
