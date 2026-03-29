#include "BottangoArduinoCallbacks.h"
#include "src/AbstractEffector.h"
#include "src/Log.h"
#include "src/Outgoing.h"
#include "src/BottangoCore.h"
#include "GeneratedCodeAnimations.h"

namespace Callbacks
{
    namespace
    {
        const char APP_ANIMATION_COMMAND[] = "APP_ANIM";
        const char START_ACTION[] = "START";
        const char STOP_ACTION[] = "STOP";
        const int DEFAULT_SPEECH_ANIMATION_INDEX = 0; // habla_normal
        const int DEFAULT_IDLE_ANIMATION_INDEX = 1;   // reposo

        bool speechAnimationRequested = false;
        int requestedAnimationIndex = DEFAULT_SPEECH_ANIMATION_INDEX;
        int activeAnimationIndex = -1;
        bool activeAnimationIsSpeech = false;
        bool activeAnimationLoops = false;

        bool isAnimationIndexValid(int animationIndex)
        {
            return animationIndex >= 0 &&
                   animationIndex < GeneratedCodeAnimations::getAnimationCount();
        }

        int resolveSpeechAnimationIndex(int animationIndex)
        {
            if (isAnimationIndexValid(animationIndex))
            {
                return animationIndex;
            }

            return isAnimationIndexValid(DEFAULT_SPEECH_ANIMATION_INDEX)
                       ? DEFAULT_SPEECH_ANIMATION_INDEX
                       : -1;
        }

        int resolveIdleAnimationIndex()
        {
            return isAnimationIndexValid(DEFAULT_IDLE_ANIMATION_INDEX)
                       ? DEFAULT_IDLE_ANIMATION_INDEX
                       : -1;
        }

        void clearManagedAnimationState()
        {
            activeAnimationIndex = -1;
            activeAnimationIsSpeech = false;
            activeAnimationLoops = false;
        }

        void startManagedAnimation(int animationIndex, bool shouldLoop, bool isSpeech)
        {
            BottangoCore::commandStreamProvider->startCommandStream((byte)animationIndex, shouldLoop);
            activeAnimationIndex = animationIndex;
            activeAnimationIsSpeech = isSpeech;
            activeAnimationLoops = shouldLoop;
        }

        void syncSpeechAnimationPlayback()
        {
#if defined(USE_CODE_COMMAND_STREAM) || defined(USE_SD_CARD_COMMAND_STREAM)
            if (BottangoCore::commandStreamProvider == nullptr)
            {
                clearManagedAnimationState();
                return;
            }

            const bool streamIsInProgress =
                BottangoCore::commandStreamProvider->streamIsInProgress();

            if (!streamIsInProgress)
            {
                clearManagedAnimationState();
            }

            const int speechAnimationIndex = resolveSpeechAnimationIndex(requestedAnimationIndex);
            const int idleAnimationIndex = resolveIdleAnimationIndex();
            const bool anotherAnimationIsPlaying =
                streamIsInProgress && activeAnimationIndex < 0;

            if (speechAnimationRequested)
            {
                if (speechAnimationIndex < 0)
                {
                    return;
                }

                // Speech runs as a finite cycle. STOP only prevents the next
                // cycle from starting, so the current arm gesture can finish.
                if (streamIsInProgress && activeAnimationIsSpeech)
                {
                    return;
                }

                startManagedAnimation(speechAnimationIndex, false, true);
                return;
            }

            // Keep idle looping when the robot is free, but avoid interrupting
            // an unrelated animation that may have been started elsewhere.
            if (anotherAnimationIsPlaying)
            {
                return;
            }

            // After STOP, let the current speech cycle end naturally before
            // switching back to the looping idle animation.
            if (streamIsInProgress && activeAnimationIsSpeech)
            {
                return;
            }

            if (idleAnimationIndex < 0)
            {
                if (activeAnimationIndex >= 0)
                {
                    BottangoCore::commandStreamProvider->stop();
                    clearManagedAnimationState();
                }
                return;
            }

            if (!streamIsInProgress ||
                activeAnimationIndex != idleAnimationIndex ||
                !activeAnimationLoops)
            {
                startManagedAnimation(idleAnimationIndex, true, false);
            }
#else
            speechAnimationRequested = false;
            requestedAnimationIndex = DEFAULT_SPEECH_ANIMATION_INDEX;
            clearManagedAnimationState();
#endif
        }
    } // namespace

    // !!!!!!!!!!!!!!! //
    // !! CONTROLLER LIFECYCLE CALLBACKS !! //
    // !!!!!!!!!!!!!!! //

    // called AFTER a successful handshake with the Bottango application, signifying that this controller has started.
    // use for general case startup process
    // Effector registration will happen after this callback, in their own callback.
    // If you have effector registration specific needs, you should use onEffectorRegistered
    void onThisControllerStarted()
    {
        speechAnimationRequested = false;
        requestedAnimationIndex = DEFAULT_SPEECH_ANIMATION_INDEX;
        clearManagedAnimationState();
    }

    // called after the controller recieves a stop command. The controller will stop all movement, deregister all effectors
    // After which this call back is triggered.
    void onThisControllerStopped()
    {
        speechAnimationRequested = false;
        requestedAnimationIndex = DEFAULT_SPEECH_ANIMATION_INDEX;
        clearManagedAnimationState();
    }

    // called each loop cycle. If you have timing based code you'd like to utilize outside of the Bottango animation
    // This callback occurs BEFORE all effectors process their movement, at the end of the loop.
    void onEarlyLoop()
    {
        syncSpeechAnimationPlayback();

        // Example for triggering animations in your own logic, while in offline (save to code / SD card) mode
        // if not playing anything, play animation index 2 (the third exported animation) and set it to looping

        // if (BottangoCore::commandStreamProvider->streamIsInProgress() == false)
        // {
        //     BottangoCore::commandStreamProvider->startCommandStream(2, true);
        // }
        // 
        // The following will stop an offline animation from playing if any
        // BottangoCore::commandStreamProvider->stop();         
    }

    // called each loop cycle.
    // This callback occurs AFTER all effectors process their movement, at the end of the loop.
    void onLateLoop()
    {

        // EX: Request stop on driver, and disconnect all active connections
        // Outgoing::outgoing_requestEStop();

        // EX: Pause Playing in App
        // Outgoing::outgoing_requestStopPlay();

        // EX: Start Playing in App (in current animation and time)
        // Outgoing::outgoing_requestStartPlay();

        // EX: Start Playing in App (with animation index, and start time in milliseconds)
        // Outgoing::outgoing_requestStartPlay(1,1000);
    }

    bool isExternalCommandAllowed(const char *commandName)
    {
        return strcmp(commandName, APP_ANIMATION_COMMAND) == 0;
    }

    bool handleExternalCommand(char **args, byte commandCount)
    {
        if (commandCount == 0 || strcmp(args[0], APP_ANIMATION_COMMAND) != 0)
        {
            return false;
        }

        if (commandCount < 2)
        {
            return true;
        }

        if (strcmp(args[1], START_ACTION) == 0)
        {
            speechAnimationRequested = true;
            if (commandCount >= 3)
            {
                requestedAnimationIndex = resolveSpeechAnimationIndex(max(0, atoi(args[2])));
            }
            else
            {
                requestedAnimationIndex = DEFAULT_SPEECH_ANIMATION_INDEX;
            }

            syncSpeechAnimationPlayback();
            return true;
        }

        if (strcmp(args[1], STOP_ACTION) == 0)
        {
            speechAnimationRequested = false;
            syncSpeechAnimationPlayback();
            return true;
        }

        return true;
    }

    // !!!!!!!!!!!!!!! //
    // !! EFFECTOR CALLBACKS !! //
    // !!!!!!!!!!!!!!! //

    // All effectors have an identifier. It is an 8 char or less string. Check Bottango to see the identifier for a given effector in app.
    // for most effectors, it is the first pin in their set of pins
    // i2c effectors have the i2c address before the first pin
    // you query for an effector with a c string char array, instanitated at 9 characters (8 for the identifier, and a null terminating char)

    // The below are called by built in effectors at various stages in their lifecycle

    // called by an effector when registered, after registration is complete
    void onEffectorRegistered(AbstractEffector *effector)
    {
        // example, turn on built in LED if effector registered with identifier "1";

        // char effectorIdentifier[9];
        // effector->getIdentifier(effectorIdentifier, 9);

        // if (strcmp(effectorIdentifier, "1") == 0)
        // {
        //     pinMode(LED_BUILTIN, OUTPUT);
        //     digitalWrite(LED_BUILTIN, HIGH);
        // }
    }

    // called by an effector when deregistered, before deregistration is complete
    void onEffectorDeregistered(AbstractEffector *effector)
    {
        // example, turn off built in LED if effector registered with identifier "1";

        // char effectorIdentifier[9];
        // effector->getIdentifier(effectorIdentifier, 9);

        // if (strcmp(effectorIdentifier, "1") == 0)
        // {
        //     pinMode(LED_BUILTIN, OUTPUT);
        //     digitalWrite(LED_BUILTIN, LOW);
        // }
    }

    // called by effectors each loop with its current signal (example: servo PWM or stepper steps from home )
    // didChange is true if different from last update called
    void effectorSignalOnLoop(AbstractEffector *effector, int signal, bool didChange)
    {
        // example, set built in led for effector with identifier "1" based on if signal is greater than 1500

        // char effectorIdentifier[9];
        // effector->getIdentifier(effectorIdentifier, 9);

        // if (strcmp(effectorIdentifier, "1") == 0)
        // {
        //     pinMode(LED_BUILTIN, OUTPUT);
        //     if (signal > 1500)
        //     {
        //         digitalWrite(LED_BUILTIN, HIGH);
        //     }
        //     else
        //     {
        //         digitalWrite(LED_BUILTIN, LOW);
        //     }
        // }

        // another example, drive a custom motor, which you have coded to have a setSignal function
        // if (strcmp(effectorIdentifier, "myMotor") == 0)
        // {
        //      myMotor->setSignal(signal);
        // }
    }

    // !!!!!!!!!!!!!!!!!!! //
    // !! CUSTOM EVENTS !! //
    // !!!!!!!!!!!!!!!!!!! //
    // The below are called by custom events so you can provide your own behaviours

    // called by a curved custom event any time the movement value is changed during a curved movement. (Movement is a normalized float between 0.0 - 1.0)
    void onCurvedCustomEventMovementChanged(AbstractEffector *effector, float newMovement)
    {
        // example, fade an led based on the new movement value
        // char effectorIdentifier[9];
        // effector->getIdentifier(effectorIdentifier, 9);

        // if (strcmp(effectorIdentifier, "myLight") == 0)
        // {
        //     pinMode(5, OUTPUT);
        //     int brightness = 255 * newMovement;
        //     analogWrite(5, brightness);
        // }
    }

    // called by a on off custom event any time the on off value is changed.
    void onOnOffCustomEventOnOffChanged(AbstractEffector *effector, bool on)
    {
        // example, turn on built in led based on the on off value
        // char effectorIdentifier[9];
        // effector->getIdentifier(effectorIdentifier, 9);

        // if (strcmp(effectorIdentifier, "myLight") == 0)
        // {
        //     pinMode(LED_BUILTIN, OUTPUT);
        //     digitalWrite(LED_BUILTIN, on ? HIGH : LOW);
        // }
    }

    // called by a trigger custom event any time the on event is triggered.
    void onTriggerCustomEventTriggered(AbstractEffector *effector)
    {
        // example, set led to a random brightness each trigger
        // char effectorIdentifier[9];
        // effector->getIdentifier(effectorIdentifier, 9);

        // if (strcmp(effectorIdentifier, "myLight") == 0)
        // {
        //     pinMode(5, OUTPUT);
        //     int brightness = random(0, 256);
        //     analogWrite(5, brightness);
        // }
    }

    void onColorCustomEventColorChanged(AbstractEffector *effector, byte newRed, byte newGreen, byte newBlue)
    {
        // example, set rgb LED on pins 3, 5, and 6 to given red, green, and blue colors (represented as a byte between 0 and 255)
        // char effectorIdentifier[9];
        // effector->getIdentifier(effectorIdentifier, 9);

        // if (strcmp(effectorIdentifier, "myRGB") == 0)
        // {
        //     pinMode(3, OUTPUT);
        //     pinMode(5, OUTPUT);
        //     pinMode(6, OUTPUT);

        //     analogWrite(3, newRed);
        //     analogWrite(5, newGreen);
        //     analogWrite(6, newBlue);
        // }

        // code free support for addressable LED's (neopixel, etc. coming soon)
        // in the meanwhile, get support in the Bottango discord channel for "how to" info
    }

    bool isStepperAutoHomeComplete(AbstractEffector *effector)
    {
        // return true if the given stepper is at home position
        // else return false

        // example, end homing on stepper with step on pin 6, when pin 10 is read high
        // char effectorIdentifier[9];
        // effector->getIdentifier(effectorIdentifier, 9);

        // if (strcmp(effectorIdentifier, "6") == 0)
        // {
        //     pinMode(10, INPUT);
        //     if (digitalRead(10) == HIGH)
        //     {
        //         return true;
        //     }
        // }

        return false;
    }
} // namespace Callbacks
