#include "state_learner.hpp"

#include <lib/nas/utils.hpp>
#include <ue/nas/task.hpp>
#include <ue/rrc/task.hpp>
#include <pthread.h>
#include <netinet/in.h>
#include <unistd.h>
#include <string>
#include <iostream>
#include <unordered_map>
#include <ue/nas/mm/dereg.cpp>
#include <lib/nas/encode.hpp>
#include <chrono>
#include <sys/un.h>
#include <sys/socket.h>
#include <arpa/inet.h>

#define LOG_LEARNER(c_str) do {\
    FILE *log = fopen("./statelearner.log", "a");\
    fprintf(log, "%s\n", (c_str));\
    fflush(log);\
    fclose(log);\
} while (0);

namespace nr::ue
{

UeStateLearner *state_learner;

int FLAG_SECMOD = 0;
bool FLAG_REPLAY = 0;
bool SMC_SENT = 0;

void* start_inet_socket(void* arg);
void* start_unix_socket(void* arg);

void UeStateLearner::startThread() 
{
    // set a seed for mutation
    srand(time(NULL));

    connfd = -1;
    pthread_t thread;

    if (conf.has_value() == false) {
        std::string family = std::string("unix");
        std::string addr = std::string("UE.sock");
        uint16_t port = 0;
        conf = StateLearnerConf{family, addr, port};
    }

    if (conf->family == "inet")
        pthread_create(&thread, NULL, start_inet_socket, (void *)&conf.value());
    else if (conf->family == "unix")
        pthread_create(&thread, NULL, start_unix_socket, (void *)&conf.value());

    pthread_detach(thread);    
}

void UeStateLearner::execute_command(std::string msg) 
{

    size_t index = msg.find("_");
    std::string msg_str = msg.substr(0, index);
    std::string sub_str = msg.substr(index + 1);

    if (msgMap.count(msg_str) == 0) 
    {
        notify_response("Unknown message name");
        return;
    }

    // set security_mode and replay flag
    FLAG_SECMOD = 0;
    FLAG_REPLAY = 0;

    NasMm* mm = m_base->nasTask->mm;
    MsgType msgType = msgMap[msg_str];

    if (!enableFuzzing) 
    {
        if (shtMap.count(sub_str) != 0) 
        {
            ShtType shtType = shtMap[sub_str];

            // set security
            switch (shtType)
            {
            case ShtType::nosec:
                FLAG_SECMOD = 1;
                break;
            case ShtType::intonly:
                FLAG_SECMOD = 2;
                break;
            case ShtType::_protected:
                FLAG_SECMOD = 3;
                break;
            case ShtType::replay:
                FLAG_REPLAY = 1;
                break;
            
            default:
                FLAG_SECMOD = 0;
                FLAG_REPLAY = 0;
                break;
            }
        }

        // send message
        switch (msgType)
        {
        case MsgType::registrationRequestIMSI:
            std::cout << "sending registrationRequestIMSI" << std::endl;
            // should get this message when UE starts
            // assume initial registration
            if (m_base->nasTask->mm->m_mmSubState != EMmSubState::MM_REGISTERED_NORMAL_SERVICE)
                mm->sendNasMessage(registrationRequestIMSI);
            else
                notify_response("null_action");
            break;
        case MsgType::registrationRequestGUTI: {
            std::cout << "sending registrationRequestGUTI" << std::endl;
            if (mm->m_storage->storedGuti->get().type == nas::EIdentityType::NO_IDENTITY)
            {
                notify_response("null_action");
                break;
            }
            else
            {
                mm->updateProvidedGuti();
                registrationRequestGUTI.mobileIdentity = mm->getOrGeneratePreferredId();
                if (mm->m_storage->lastVisitedRegisteredTai->get().hasValue())
                    registrationRequestGUTI.lastVisitedRegisteredTai = nas::IE5gsTrackingAreaIdentity{mm->m_storage->lastVisitedRegisteredTai->get()};
                // Assign ngKSI
                if (mm->m_usim->m_currentNsCtx)
                {
                    registrationRequestGUTI.nasKeySetIdentifier.tsc = mm->m_usim->m_currentNsCtx->tsc;
                    registrationRequestGUTI.nasKeySetIdentifier.ksi = mm->m_usim->m_currentNsCtx->ngKsi;
                }
                mm->sendNasMessage(registrationRequestGUTI);
            }       
            break;}
        case MsgType::registrationComplete:
            std::cout << "sending registrationComplete" << std::endl;
            mm->sendNasMessage(nas::RegistrationComplete{});
            break;
        case MsgType::deregistrationRequest:
            std::cout << "sending deregistrationRequest" << std::endl;
            if (!storedMsgCount[(int)MsgType::deregistrationRequest])
            {
                deregistrationRequest.deRegistrationType = MakeDeRegistrationType(EDeregCause::NORMAL);
                deregistrationRequest.ngKSI.ksi = nas::IENasKeySetIdentifier::NOT_AVAILABLE_OR_RESERVED;
                deregistrationRequest.ngKSI.tsc = nas::ETypeOfSecurityContext::NATIVE_SECURITY_CONTEXT;
                deregistrationRequest.mobileIdentity = m_base->nasTask->mm->getOrGeneratePreferredId();
                storedMsgCount[(int)MsgType::deregistrationRequest]++;
            }
            mm->sendNasMessage(deregistrationRequest);
            break;
        case MsgType::serviceRequest:
            std::cout << "sending serviceRequest" << std::endl;
            if (!storedMsgCount[(int)MsgType::serviceRequest])
            {
                serviceRequest.serviceType.serviceType = nas::EServiceType::DATA;
                if (!mm->m_usim->isValid())
                {
                    serviceRequest.ngKSI.tsc = mm->m_usim->m_currentNsCtx->tsc;
                    serviceRequest.ngKSI.ksi = mm->m_usim->m_currentNsCtx->ngKsi;
                }
                // Assign TMSI (TMSI is a part of GUTI)
                serviceRequest.tmsi.type = nas::EIdentityType::TMSI;
                serviceRequest.tmsi.gutiOrTmsi.plmn = {};
                serviceRequest.tmsi.gutiOrTmsi.amfRegionId = {};
                storedMsgCount[(int)MsgType::serviceRequest]++;
            }
            // trigger new serviceRequest
            mm->sendServiceRequest(EServiceReqCause::IDLE_UPLINK_SIGNAL_PENDING);
            mm->sendNasMessage(serviceRequest);
            break;
        case MsgType::securityModeReject: {
            std::cout << "sending securityModeReject" << std::endl;
            securityModeReject.mmCause.value = nas::EMmCause::SEC_MODE_REJECTED_UNSPECIFIED;
            mm->sendNasMessage(securityModeReject);
            break;}
        case MsgType::authenticationResponse:
            std::cout << "sending authenticationResponse" << std::endl;
            if (!storedMsgCount[(int)MsgType::authenticationResponse])
            {
                authenticationResponse.authenticationResponseParameter = nas::IEAuthenticationResponseParameter{};
                authenticationResponse.authenticationResponseParameter->rawData = mm->m_usim->m_resStar.copy();
                storedMsgCount[(int)MsgType::authenticationResponse]++;
            }
            mm->sendNasMessage(authenticationResponse);
            break;
        case MsgType::authenticationResponseEmpty:{
            nas::AuthenticationResponse resp;
            resp.authenticationResponseParameter = nas::IEAuthenticationResponseParameter{};
            std::cout << "sending authenticationResponseEmpty" << std::endl;
            mm->sendNasMessage(resp);
            break;}
        case MsgType::authenticationFailure:{
            nas::AuthenticationFailure resp;
            resp.mmCause.value = nas::EMmCause::UNSPECIFIED_PROTOCOL_ERROR;
            std::cout << "sending authenticationFailure" << std::endl;
            mm->sendNasMessage(resp);
            break;}
        case MsgType::deregistrationAccept:
            std::cout << "sending deregistrationAccept" << std::endl;
            mm->sendNasMessage(nas::DeRegistrationAcceptUeTerminated{});
            break;
        case MsgType::securityModeComplete:{
            if (FLAG_REPLAY == 1)
            {
                if (SMC_SENT == 1)
                {
                    std::cout << "sending securityModeComplete_replay" << std::endl;
                    mm->sendNasMessage(securityModeComplete_replay);
                }
                else 
                {
                    notify_response("null_action");
                }
                break;
            }
            SMC_SENT = 1;
            // store msg for replay
            auto copy = nas::utils::DeepCopyMsg(securityModeComplete);
            securityModeComplete_replay = std::move((nas::SecurityModeComplete&) *copy);
            std::cout << "sending securityModeComplete" << std::endl;
            // don't need to set any fields
            mm->sendNasMessage(securityModeComplete);
            break;}
        case MsgType::identityResponse:
            std::cout << "sending identityResponse" << std::endl;
            if (!storedMsgCount[(int)MsgType::identityResponse])
            {
                identityResponse.mobileIdentity = mm->getOrGenerateSuci();
                storedMsgCount[(int)MsgType::identityResponse]++;
            }
            // handle incorrect transition in open5gs
            if (m_base->nasTask->mm->m_mmSubState != EMmSubState::MM_REGISTERED_NORMAL_SERVICE)
                mm->sendNasMessage(identityResponse);
            else
                notify_response("null_action");
            break;
        case MsgType::configurationUpdateComplete:
            std::cout << "sending configurationUpdateComplete" << std::endl;
            mm->sendNasMessage(nas::ConfigurationUpdateComplete{});
            break;

        // not used for now
        // case MsgType::ulNasTransport:
        //     std::cout << "sending ulNasTransport" << std::endl;
        //     mm->sendNasMessage(nas::UlNasTransport{});
        //     break;
        // case MsgType::gmmStatus: {
        //     std::cout << "sending gmmStatus" << std::endl;
        //     gmmStatus.mmCause.value = nas::EMmCause::UNSPECIFIED_PROTOCOL_ERROR;
        //     mm->sendNasMessage(gmmStatus);
            // break;}

        // fuzzing
        case MsgType::enableFuzzing:
            std::cout << "enable fuzzing" << std::endl;
            notify_response("Start fuzzing");
            enableFuzzing = true;
            break;
        // send the a message from db to the Core
        case MsgType::testMessage:{
            testMessage = true;
            notify_response("OK");
            std::cout << "testMessage" << std::endl;
            // get size of binary message
            size_t size = 1000;
            // get string size from message
            if (index != std::string::npos)
                size = std::stoi(sub_str);
            // get message
            char* buffer = (char*)calloc(size+1, sizeof(char));
            int valread = read(connfd, buffer, size+1); // read (block)
            if (connfd < 0) 
            {
                perror("No connection to CoreFuzzer\n");
                exit(1);
            }
            std::string msgIn(buffer, valread);
            printf("Read %d bytes from CoreFuzzer\n", valread);
            printf("Message: %s\n", msgIn.c_str());
            std::cout << std::endl; // flush
            size_t c1 = msgIn.find_first_of(":");
            size_t c2 = msgIn.find_last_of(":");
            // set pdu
            OctetString pdu = OctetString::FromHex(msgIn.substr(0, c1));
            // set SECMOD
            FLAG_SECMOD = std::stoi(msgIn.substr(c1+1, c2-c1-1));
            // set sht
            control_sht = std::stoi(msgIn.substr(c2+1));
            // send the message directly to avoid decode error
            if (FLAG_SECMOD == 1 && control_sht == 0)
            {
                auto m = std::make_unique<NmUeNasToRrc>(NmUeNasToRrc::UPLINK_NAS_DELIVERY);
                m->pduId = 0;
                m->nasPdu = std::move(pdu);
                m_base->rrcTask->push(std::move(m));
            }
            else
            {
                auto msg = nas::DecodeNasMessage(OctetView{pdu});
                mm->sendNasMessage((nas::PlainMmMessage &) *msg);
            }

            testMessage = false;
            break;}

        case MsgType::aflnetMessage:
        {
            std::cerr << "aflnetMessage" << std::endl;
            std::cerr << msg_str << " " << sub_str << std::endl;

            size_t c1 = sub_str.find_first_of(":");
            size_t c2 = sub_str.find_last_of(":");
            if (c1 == std::string::npos || c2 == std::string::npos || c1 == c2) {
                notify_response("UNKNOWN");
                break;
            }

            try {
                // set pdu
                OctetString pdu = OctetString::FromHex(sub_str.substr(0, c1));
                // set SECMOD
                FLAG_SECMOD = std::stoi(sub_str.substr(c1+1, c2-c1-1));
                // set sht
                control_sht = std::stoi(sub_str.substr(c2+1));

                auto msg = nas::DecodeNasMessage(OctetView{pdu});
                mm->sendNasMessage((nas::PlainMmMessage &)*msg);
            } catch (std::runtime_error const &ex) {
                notify_response("UNKNOWN");
            } catch (std::invalid_argument const& ex) {
                notify_response("UNKNOWN");
            } catch (std::out_of_range const& ex) {
                notify_response("UNKNOWN");
            }


            break;
        }

        default:
            std::cout << "Unknown message name" << std::endl;
            notify_response("Unknown message name");
            break;
        }
    }
    else
    {
        // naive AFL fuzzing
        // custom mutator fuzzing
        // send message to corefuzzer
        OctetString stream;
        // prepare response message
        response_t resp;
        response = &resp;
        switch (msgType)
        {
        case MsgType::enableFuzzing:
            std::cout << "enable fuzzing" << std::endl;
            notify_response("Start fuzzing");
            enableFuzzing = true;
            break;
        case MsgType::registrationRequestIMSI:
            std::cout << "sending registrationRequestIMSI to fuzzer" << std::endl;
            // should get this message when UE starts
            // assume initial registration
            nas::EncodeNasMessage((nas::PlainMmMessage &)registrationRequestIMSI, stream);
            response->new_msg = stream.toHexString();
            // std::cout << "stream.toHexString()" << stream.toHexString() << std::endl;
            // somehow the string here is longer than the pdu being sent, chek if there will be any problem
            send_response_message(response);
            break;
        case MsgType::registrationComplete:{
            std::cout << "sending registrationComplete to fuzzer" << std::endl;
            auto basemsg = nas::RegistrationComplete{};
            nas::EncodeNasMessage((nas::PlainMmMessage &) basemsg, stream);
            response->new_msg = stream.toHexString();
            send_response_message(response);
            break;}
        case MsgType::deregistrationRequest:
            std::cout << "sending deregistrationRequest to fuzzer" << std::endl;
            if (!storedMsgCount[(int)MsgType::deregistrationRequest])
            {
                deregistrationRequest.deRegistrationType = MakeDeRegistrationType(EDeregCause::NORMAL);
                deregistrationRequest.ngKSI.ksi = nas::IENasKeySetIdentifier::NOT_AVAILABLE_OR_RESERVED;
                deregistrationRequest.ngKSI.tsc = nas::ETypeOfSecurityContext::NATIVE_SECURITY_CONTEXT;
                deregistrationRequest.mobileIdentity = m_base->nasTask->mm->getOrGeneratePreferredId();
                storedMsgCount[(int)MsgType::deregistrationRequest]++;
            }
            nas::EncodeNasMessage((nas::PlainMmMessage &) deregistrationRequest, stream);
            response->new_msg = stream.toHexString();
            send_response_message(response);
            break;
        case MsgType::serviceRequest:
            std::cout << "sending serviceRequest to fuzzer" << std::endl;
            if (!storedMsgCount[(int)MsgType::serviceRequest])
            {
                serviceRequest.serviceType.serviceType = nas::EServiceType::DATA;
                if (!mm->m_usim->isValid())
                {
                    serviceRequest.ngKSI.tsc = mm->m_usim->m_currentNsCtx->tsc;
                    serviceRequest.ngKSI.ksi = mm->m_usim->m_currentNsCtx->ngKsi;
                }
                // Assign TMSI (TMSI is a part of GUTI)
                serviceRequest.tmsi.type = nas::EIdentityType::TMSI;
                serviceRequest.tmsi.gutiOrTmsi.plmn = {};
                serviceRequest.tmsi.gutiOrTmsi.amfRegionId = {};
                storedMsgCount[(int)MsgType::serviceRequest]++;
            }
            // trigger new serviceRequest
            mm->sendServiceRequest(EServiceReqCause::IDLE_UPLINK_SIGNAL_PENDING);
            nas::EncodeNasMessage((nas::PlainMmMessage &) serviceRequest, stream);
            response->new_msg = stream.toHexString();
            send_response_message(response);
            break;
        case MsgType::securityModeReject: {
            std::cout << "sending securityModeReject to fuzzer" << std::endl;
            securityModeReject.mmCause.value = nas::EMmCause::SEC_MODE_REJECTED_UNSPECIFIED;
            nas::EncodeNasMessage((nas::PlainMmMessage &) securityModeReject, stream);
            response->new_msg = stream.toHexString();
            send_response_message(response);
            break;}
        case MsgType::authenticationResponse:
            std::cout << "sending authenticationResponse to fuzzer" << std::endl;
            if (!storedMsgCount[(int)MsgType::authenticationResponse])
            {
                authenticationResponse.authenticationResponseParameter = nas::IEAuthenticationResponseParameter{};
                authenticationResponse.authenticationResponseParameter->rawData = mm->m_usim->m_resStar.copy();
                storedMsgCount[(int)MsgType::authenticationResponse]++;
            }
            nas::EncodeNasMessage((nas::PlainMmMessage &) authenticationResponse, stream);
            response->new_msg = stream.toHexString();
            send_response_message(response);
            break;
        case MsgType::authenticationResponseEmpty:{
            nas::AuthenticationResponse resp;
            resp.authenticationResponseParameter = nas::IEAuthenticationResponseParameter{};
            std::cout << "sending authenticationResponseEmpty to fuzzer" << std::endl;
            nas::EncodeNasMessage((nas::PlainMmMessage &) resp, stream);
            response->new_msg = stream.toHexString();
            send_response_message(response);
            break;}
        case MsgType::authenticationFailure:{
            nas::AuthenticationFailure resp;
            resp.mmCause.value = nas::EMmCause::UNSPECIFIED_PROTOCOL_ERROR;
            std::cout << "sending authenticationFailure to fuzzer" << std::endl;
            nas::EncodeNasMessage((nas::PlainMmMessage &) resp, stream);
            response->new_msg = stream.toHexString();
            send_response_message(response);
            break;}
        case MsgType::deregistrationAccept:{
            std::cout << "sending deregistrationAccept to fuzzer" << std::endl;
            auto basemsg = nas::DeRegistrationAcceptUeTerminated{};
            nas::EncodeNasMessage((nas::PlainMmMessage &) basemsg, stream);
            response->new_msg = stream.toHexString();
            send_response_message(response);
            break;}
        case MsgType::securityModeComplete:
            // store msg for replay
            std::cout << "sending securityModeComplete to fuzzer" << std::endl;
            // don't need to set any fields
            nas::EncodeNasMessage((nas::PlainMmMessage &) securityModeComplete, stream);
            response->new_msg = stream.toHexString();
            send_response_message(response);
            break;
        case MsgType::identityResponse:
            std::cout << "sending identityResponse to fuzzer" << std::endl;
            if (!storedMsgCount[(int)MsgType::identityResponse])
            {
                identityResponse.mobileIdentity = mm->getOrGenerateSuci();
                storedMsgCount[(int)MsgType::identityResponse]++;
            }
            nas::EncodeNasMessage((nas::PlainMmMessage &) identityResponse, stream);
            response->new_msg = stream.toHexString();
            send_response_message(response);
            break;
        case MsgType::configurationUpdateComplete:{
            std::cout << "sending configurationUpdateComplete to fuzzer" << std::endl;
            auto basemsg = nas::ConfigurationUpdateComplete{};
            nas::EncodeNasMessage((nas::PlainMmMessage &) basemsg, stream);
            response->new_msg = stream.toHexString();
            send_response_message(response);
            break;}
        case MsgType::gmmStatus: {
            std::cout << "sending gmmStatus to fuzzer" << std::endl;
            auto basemsg = nas::FiveGMmStatus{};
            basemsg.mmCause.value = nas::EMmCause::UNSPECIFIED_PROTOCOL_ERROR;
            nas::EncodeNasMessage((nas::PlainMmMessage &) basemsg, stream);
            response->new_msg = stream.toHexString();
            send_response_message(response);
            break;}
        case MsgType::ulNasTransport: {
            std::cout << "sending ulNasTransport to fuzzer" << std::endl;
            auto basemsg = nas::UlNasTransport{};
            nas::EncodeNasMessage((nas::PlainMmMessage &) basemsg, stream);
            response->new_msg = stream.toHexString();
            send_response_message(response);
            break;}
        case MsgType::incomingMessage:{
            notify_response("OK");
            std::cout << "incomingMessage" << std::endl;
            // get size of binary message
            size_t size = 1000;
            // get string size from message
            if (index != std::string::npos)
                size = std::stoi(sub_str);
            // get binary message
            OctetString pdu = recv_incoming_message(size);
            // send binary message to corefuzzer
            dec_before_mut = true;
            auto msg = nas::DecodeNasMessage(OctetView{pdu});
            dec_before_mut = false;
            MutateNasMessage(*msg.get());
            std::cout << "mutate complete" << std::endl;

            // change secmod
            response->secmod = nas::mutate_secmod();
            mm->sendNasMessage((nas::PlainMmMessage &) *msg);
            FLAG_SECMOD = 1; // for encode plaintext message
            nas::EncodeNasMessage((nas::PlainMmMessage &) *msg, stream);
            response->new_msg = stream.toHexString();

            // wait for response (max 0.5s)
            for (int i = 0; i < 10; i++)
            {
                if (response->ret_msg != "" && response->ret_type != "")
                    break;
                std::this_thread::sleep_for(std::chrono::milliseconds(50));
            }

            send_response_message(response); // MM only for now
            break;}
        // send the a message from db to the Core
        case MsgType::testMessage:{
            enableFuzzing = false;
            testMessage = true;
            notify_response("OK");
            std::cout << "testMessage" << std::endl;
            // get size of binary message
            size_t size = 1000;
            // get string size from message
            if (index != std::string::npos)
                size = std::stoi(sub_str);
            // get message
            char* buffer = (char*)calloc(size+1, sizeof(char));
            int valread = read(connfd, buffer, size+1); // read (block)
            if (connfd < 0) 
            {
                perror("No connection to CoreFuzzer\n");
                exit(1);
            }
            std::string msgIn(buffer, valread);
            printf("Read %d bytes from CoreFuzzer\n", valread);
            printf("Message: %s\n", msgIn.c_str());

            size_t c1 = msgIn.find_first_of(":");
            size_t c2 = msgIn.find_last_of(":");
            // set pdu
            OctetString pdu = OctetString::FromHex(msgIn.substr(0, c1));
            // set SECMOD
            FLAG_SECMOD = std::stoi(msgIn.substr(c1+1, c2-c1-1));
            // set sht
            control_sht = std::stoi(msgIn.substr(c2+1));
            auto msg = nas::DecodeNasMessage(OctetView{pdu});
            mm->sendNasMessage((nas::PlainMmMessage &) *msg);

            testMessage = false;
            enableFuzzing = true;
            break;}
        // send the message as-is to the Core
        case MsgType::rawMessage:{
            enableFuzzing = false;
            notify_response("OK");
            std::cout << "rawMessage" << std::endl;
            // get size of binary message
            size_t size = 1000;
            // get string size from message
            if (index != std::string::npos)
                size = std::stoi(sub_str);
            // get binary message
            OctetString pdu = recv_incoming_message(size);

            auto m = std::make_unique<NmUeNasToRrc>(NmUeNasToRrc::UPLINK_NAS_DELIVERY);
            m->pduId = 0;
            m->nasPdu = std::move(pdu);
            m_base->rrcTask->push(std::move(m));

            enableFuzzing = true;
            break;}

        default:
            std::cout << "Unknown fuzzing message name" << std::endl;
            notify_response("Unknown fuzzing message name");
            break;
        }
        response = nullptr;
    }
}

void UeStateLearner::notify_response(std::string msg) 
{
    std::cout << "notify_response " << msg << std::endl;
    msg.append("\n");
    if (connfd < 0) 
    {
        fprintf(stderr, "No connection to statelearner\n");
        return;
    }
    
    if ((send(connfd, msg.c_str(), msg.length(), 0)) < 0) 
    {
        perror("Error in Send to Statelearner\n");
        assert(0);
        return;
    }
}

void UeStateLearner::send_response_message(response_t* response) 
{
    // printf("Sending response to statelearner\n");

    // std::string msg = "binary_message:";
    std::string resp_str = response->ToJson();
    // msg.append(std::to_string(resp_str.length()));
    std::cout << "send to fuzzer: " << response->new_msg << std::endl;
    // notify_response(msg);
    notify_response(resp_str);
}

OctetString UeStateLearner::recv_incoming_message(size_t size) 
{
    // make sure the buffer is big enough 
    char* buffer = (char*)calloc(size+1, sizeof(char));
    int valread = read(connfd, buffer, size+1); // read (block)
    if (connfd < 0) 
    {
        perror("No connection to CoreFuzzer\n");
        exit(1);
    }
    std::string msg(buffer, valread);
    printf("Read %d bytes from CoreFuzzer\n", valread);
    printf("Message: %s\n", msg.c_str());
    // printf("Message length: %d\n", msg.length());
    OctetString base = OctetString::FromHex(msg);
    free(buffer);
    return base;
}

bool UeStateLearner::has_sec_ctx() 
{
    if (m_base->nasTask->mm->m_usim->m_currentNsCtx != nullptr)
        return true;
    else
        return false;
}

void UeStateLearner::store_message(nas::PlainMmMessage &msg) 
{
    auto copy = nas::utils::DeepCopyMsg(msg);
    switch (msg.messageType)
    {
    case nas::EMessageType::REGISTRATION_REQUEST:
        if (init_reg)
        {
            registrationRequestIMSI = std::move((nas::RegistrationRequest&) *copy);
            registrationRequestGUTI = std::move((nas::RegistrationRequest&) *copy);
        }   
        break;
    case nas::EMessageType::REGISTRATION_COMPLETE:
        // registrationComplete = std::move((nas::RegistrationComplete&) *copy);
        break;
    case nas::EMessageType::DEREGISTRATION_REQUEST_UE_ORIGINATING:
        deregistrationRequest = std::move((nas::DeRegistrationRequestUeOriginating&) *copy);
        break;
    case nas::EMessageType::SERVICE_REQUEST:
        serviceRequest = std::move((nas::ServiceRequest&) *copy);
        break;
    case nas::EMessageType::SECURITY_MODE_REJECT:
        // securityModeReject = std::move((nas::SecurityModeReject&) *copy);
        break;
    case nas::EMessageType::AUTHENTICATION_RESPONSE:  
        authenticationResponse = std::move((nas::AuthenticationResponse&) *copy);
        break;
    case nas::EMessageType::AUTHENTICATION_FAILURE:
        authenticationFailure = std::move((nas::AuthenticationFailure&) *copy);
        break;
    case nas::EMessageType::DEREGISTRATION_ACCEPT_UE_TERMINATED:
        // deregistrationAccept = std::move((nas::DeRegistrationAcceptUeTerminated&) *copy);
        break;
    case nas::EMessageType::SECURITY_MODE_COMPLETE:
        // Do not use copyed message, since deep copy add 0 at the end of IMEISV
        securityModeComplete = std::move((nas::SecurityModeComplete&) msg);
        break;
    case nas::EMessageType::IDENTITY_RESPONSE:
        identityResponse = std::move((nas::IdentityResponse&) *copy);
        break;
    case nas::EMessageType::FIVEG_MM_STATUS:
        // gmmStatus = std::move((nas::FiveGMmStatus&) *copy);
        break;
    case nas::EMessageType::CONFIGURATION_UPDATE_COMPLETE:
        // configurationUpdateComplete = std::move((nas::ConfigurationUpdateComplete&) *copy);
        break;
    case nas::EMessageType::UL_NAS_TRANSPORT:
        // ulNasTransport = std::move((nas::UlNasTransport&) *copy);
        break;
    
    default:
        break;
    }
}

nas::IE5gsMobileIdentity UeStateLearner::getOrGenerateId(nas::EIdentityType idType)
{
    switch (idType)
    {
    case nas::EIdentityType::GUTI:
        return m_base->nasTask->mm->m_storage->storedGuti->get();
    case nas::EIdentityType::SUCI:
        return m_base->nasTask->mm->getOrGenerateSuci();
    case nas::EIdentityType::IMEI:{
        nas::IE5gsMobileIdentity res{};
        res.type = nas::EIdentityType::IMEI;
        res.value = *m_base->config->imei;
        return res;}
    case nas::EIdentityType::TMSI:
        // TMSI is already a part of GUTI
        return  m_base->nasTask->mm->m_storage->storedGuti->get();
    case nas::EIdentityType::IMEISV:{
        nas::IE5gsMobileIdentity res{};
        res.type = nas::EIdentityType::IMEISV;
        res.value = *m_base->config->imeiSv;
        return res;}
    case nas::EIdentityType::NO_IDENTITY:{
        nas::IE5gsMobileIdentity res{};
        res.type = nas::EIdentityType::NO_IDENTITY;
        return res;}
    default:
        return nas::IE5gsMobileIdentity{};
    }
}

void* start_unix_socket(void* arg)
{
    StateLearnerConf *conf = (StateLearnerConf *)arg;
    if (conf == nullptr) {
        fprintf(stderr, "Null StateLearnerConf instance\n");
        exit(1);
    }

    struct sockaddr_un addr, client_addr;
    size_t addrlen = 0, client_addrlen = 0;
    int fd = -1;

    fd = socket(AF_UNIX, SOCK_STREAM, 0);

    addr.sun_family = AF_UNIX;
    strcpy(addr.sun_path, conf->addr.c_str());
    unlink(addr.sun_path);

    if (fd < 0) 
    {
        fprintf(stderr, "Could not create socket: %s\n", strerror(errno));
        exit(1);
    }

    if (bind(fd, (struct sockaddr *)&addr, addrlen) < 0) 
    {
        fprintf(stderr, "Could not bind socket: %s\n", strerror(errno));
        goto error;
    }

    if (listen(fd, 1) < 0) 
    {
        fprintf(stderr, "Could not listen on socket: %s\n", strerror(errno));
        goto error;
    }

    fprintf(stderr, "Waiting for %s connection\n", conf->family.c_str());
    
    state_learner->connfd = accept(fd, (struct sockaddr *)&client_addr, (socklen_t *)&client_addrlen);
    if (state_learner->connfd < 0) 
    {
        fprintf(stderr, "Could not accept connection: %s\n", strerror(errno));
        goto error;
    }

    LOG_LEARNER("Connection Accepted");

    for(;;) 
    {
        char buffer[1024] = {0};
        int valread = read(state_learner->connfd, buffer, 1024); // read (block)
        if (valread < 0) 
        {
            fprintf(stderr, "Could not read from socket: %s\n", strerror(errno));
            goto error;
        }
        else if (valread == 0) 
        {
            fprintf(stderr, "Connection closed\n");
            close(state_learner->connfd);
            state_learner->connfd = accept(fd, (struct sockaddr *)&client_addr, (socklen_t *)&client_addrlen);
            continue;
        }
        else 
        {
            fprintf(stderr, "Read %d bytes from socket\n", valread);
            std::string msg(buffer, valread);
            LOG_LEARNER(msg.c_str());
            if (msg.compare("Hello\n") == 0) 
            {
                state_learner->notify_response("Hi");
                continue;
            }
            state_learner->execute_command(msg);
        }
    }
    close(state_learner->connfd);
    close(fd);
    return NULL;
error:
    close(state_learner->connfd);
    close(fd);
    exit(1);
}

void* start_inet_socket(void* arg)
{
    StateLearnerConf *conf = (StateLearnerConf *)arg;
    if (conf == nullptr) {
        fprintf(stderr, "Null StateLearnerConf instance\n");
        exit(1);
    }

    struct sockaddr_in addr, client_addr;
    size_t addrlen = 0, client_addrlen = 0;
    int fd = -1;

    fd = socket(AF_INET, SOCK_STREAM, 0);

    const int enable = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &enable, sizeof (int));

    addr.sin_family = AF_INET;
    if (conf->addr == "any")
        addr.sin_addr.s_addr = htonl(INADDR_ANY);
    else
        addr.sin_addr.s_addr = inet_addr(conf->addr.c_str());
    addr.sin_port = htons(conf->port);

    addrlen = sizeof (addr);

    if (fd < 0) 
    {
        fprintf(stderr, "Could not create socket: %s\n", strerror(errno));
        exit(1);
    }

    if (bind(fd, (struct sockaddr *)&addr, addrlen) < 0) 
    {
        fprintf(stderr, "Could not bind socket: %s\n", strerror(errno));
        goto error;
    }

    if (listen(fd, 1) < 0) 
    {
        fprintf(stderr, "Could not listen on socket: %s\n", strerror(errno));
        goto error;
    }

    fprintf(stderr, "Waiting for %s connection\n", conf->family.c_str());

    state_learner->connfd = accept(fd, (struct sockaddr *)&client_addr, (socklen_t *)&client_addrlen);
    if (state_learner->connfd < 0) 
    {
        fprintf(stderr, "Could not accept connection: %s\n", strerror(errno));
        goto error;
    }

    LOG_LEARNER("Connection Accepted");

    for(;;) 
    {
        char buffer[1024] = {0};
        int valread = read(state_learner->connfd, buffer, 1024); // read (block)
        if (valread < 0) 
        {
            fprintf(stderr, "Could not read from socket: %s\n", strerror(errno));
            goto error;
        }
        else if (valread == 0) 
        {
            fprintf(stderr, "Connection closed\n");
            close(state_learner->connfd);
            state_learner->connfd = accept(fd, (struct sockaddr *)&client_addr, (socklen_t *)&client_addrlen);
            continue;
        }
        else 
        {
            fprintf(stderr, "Read %d bytes from socket\n", valread);
            std::string msg(buffer, valread);
            LOG_LEARNER(msg.c_str());
            if (msg.compare("Hello\n") == 0) 
            {
                state_learner->notify_response("Hi");
                continue;
            }
            state_learner->execute_command(msg);
        }
    }
    close(state_learner->connfd);
    close(fd);
    return NULL;
error:
    close(state_learner->connfd);
    close(fd);
    exit(1);
}

} // namespace nr::ue
