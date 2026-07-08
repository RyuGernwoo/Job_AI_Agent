"""Streamlit UI for the LectureOps Agent MVP."""

from pathlib import Path
import sys
import tempfile

SRC_ROOT = Path(__file__).resolve().parents[2]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import streamlit as st

from lectureops_agent.models.schemas import NCSUnit, PackageStatus, ProjectCreate
from lectureops_agent.services.export_service import export_lesson_package_docx
from lectureops_agent.services.parser_service import decode_text_material
from lectureops_agent.ui.workflow import (
    approve_package,
    mark_reviewed,
    parse_multiline_items,
    run_text_material_workflow,
)


def main() -> None:
    st.set_page_config(page_title="LectureOps Agent MVP", layout="wide")
    st.title("LectureOps Agent MVP")

    if "package" not in st.session_state:
        st.session_state.package = None
    if "workflow" not in st.session_state:
        st.session_state.workflow = None

    with st.sidebar:
        st.header("상태")
        package = st.session_state.package
        if package is None:
            st.info("패키지 미생성")
        else:
            st.metric("패키지 상태", package.status.value)
            st.caption(f"Package ID: {package.package_id}")

    input_col, result_col = st.columns([0.45, 0.55], gap="large")

    with input_col:
        st.subheader("강의 패키지 입력")
        with st.form("lectureops-input"):
            course_title = st.text_input("과정명", value="Generative AI Python Basics")
            lesson_title = st.text_input("차시명", value="Python functions and prompt automation practice")
            learner_profile = st.text_area(
                "학습자 프로필",
                value="Job training learners with basic Python experience",
                height=80,
            )
            learning_objectives_text = st.text_area(
                "학습 목표",
                value="Explain function inputs and return values.\nWrite a simple prompt automation function.",
                height=100,
            )
            ncs_unit_code = st.text_input("NCS 능력단위 코드", value="MVP-NCS-001")
            ncs_unit_name = st.text_input("NCS 능력단위명", value="AI-assisted programming basics")
            ncs_elements_text = st.text_area(
                "NCS 수행 요소",
                value="Analyze requirements and write simple automation code.",
                height=80,
            )
            uploaded_file = st.file_uploader("교재 파일", type=["txt", "md", "pdf"])
            retrieval_query = st.text_input("검색 query", value="return output")
            top_k = st.number_input("검색 chunk 수", min_value=1, max_value=10, value=3, step=1)
            submitted = st.form_submit_button("패키지 생성")

        if submitted:
            _handle_submit(
                course_title=course_title,
                lesson_title=lesson_title,
                learner_profile=learner_profile,
                learning_objectives_text=learning_objectives_text,
                ncs_unit_code=ncs_unit_code,
                ncs_unit_name=ncs_unit_name,
                ncs_elements_text=ncs_elements_text,
                uploaded_file=uploaded_file,
                retrieval_query=retrieval_query,
                top_k=int(top_k),
            )

    with result_col:
        _render_result_panel()


def _handle_submit(
    *,
    course_title: str,
    lesson_title: str,
    learner_profile: str,
    learning_objectives_text: str,
    ncs_unit_code: str,
    ncs_unit_name: str,
    ncs_elements_text: str,
    uploaded_file,
    retrieval_query: str,
    top_k: int,
) -> None:
    learning_objectives = parse_multiline_items(learning_objectives_text)
    ncs_elements = parse_multiline_items(ncs_elements_text)
    if not learning_objectives:
        st.error("학습 목표를 1개 이상 입력하십시오.")
        return
    if uploaded_file is None:
        st.error("TXT, MD, PDF 중 하나의 교재 파일을 업로드하십시오.")
        return

    try:
        text, source_type = decode_text_material(uploaded_file.name, uploaded_file.getvalue())
        project_input = ProjectCreate(
            course_title=course_title,
            lesson_title=lesson_title,
            learner_profile=learner_profile,
            learning_objectives=learning_objectives,
            ncs_units=[
                NCSUnit(unit_code=ncs_unit_code, unit_name=ncs_unit_name, elements=ncs_elements)
            ],
        )
        workflow = run_text_material_workflow(
            project_input=project_input,
            material_name=uploaded_file.name,
            source_type=source_type,
            text=text,
            retrieval_query=retrieval_query,
            top_k=top_k,
        )
    except ValueError as exc:
        st.error(str(exc))
        return

    st.session_state.workflow = workflow
    st.session_state.package = workflow.package
    st.success("패키지 초안을 생성했습니다.")


def _render_result_panel() -> None:
    workflow = st.session_state.workflow
    package = st.session_state.package
    if workflow is None or package is None:
        st.subheader("생성 결과")
        st.info("왼쪽 입력 영역에서 교재를 업로드하고 패키지를 생성하십시오.")
        return

    st.subheader("생성 결과")
    st.caption(f"Chunks: {len(workflow.chunks)} / Retrieved: {len(workflow.retrieved_chunks)}")

    tab_plan, tab_practice, tab_assessment, tab_export = st.tabs(["교안", "실습", "평가", "검토/다운로드"])
    with tab_plan:
        st.markdown(f"### {package.lesson_plan.title}")
        for flow in package.lesson_plan.lecture_flow:
            st.markdown(f"#### {flow.section}")
            st.write(flow.content)
            st.caption("citations: " + ", ".join(flow.citation_ids))

    with tab_practice:
        st.write(package.practice.scenario)
        st.markdown("#### 단계")
        for index, step in enumerate(package.practice.steps, start=1):
            st.write(f"{index}. {step}")
        st.markdown("#### 루브릭")
        for item in package.practice.rubric:
            st.write(f"- {item}")

    with tab_assessment:
        for index, question in enumerate(package.assessment.multiple_choice, start=1):
            st.markdown(f"#### Q{index}. {question.question}")
            for option_index, option in enumerate(question.options, start=1):
                st.write(f"{option_index}. {option}")
            st.caption(f"answer: {question.answer_index + 1} / citations: {', '.join(question.citation_ids)}")

    with tab_export:
        st.write(f"현재 상태: `{package.status.value}`")
        col_review, col_approve = st.columns(2)
        with col_review:
            if st.button("검토 완료", use_container_width=True):
                st.session_state.package = mark_reviewed(package)
                st.rerun()
        with col_approve:
            if st.button("승인", use_container_width=True):
                st.session_state.package = approve_package(package)
                st.rerun()

        if st.session_state.package.status == PackageStatus.APPROVED:
            output_path = Path(tempfile.gettempdir()) / "lectureops_agent_streamlit" / f"{package.package_id}.docx"
            export_lesson_package_docx(package=st.session_state.package, output_path=output_path)
            st.download_button(
                "DOCX 다운로드",
                data=output_path.read_bytes(),
                file_name=f"{package.package_id}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
        else:
            st.info("DOCX 다운로드는 승인 상태에서만 활성화됩니다.")


if __name__ == "__main__":
    main()
