import { Component, OnInit } from "@angular/core";
import { EventBusService } from "../../../services/communication.service";
import {gsap} from "gsap";

@Component({
    selector: "app-navbar",
    standalone: true,
    templateUrl: "./navbar.html",
    styleUrls: ["./navbar.scss"]
})

export class NavBar implements OnInit{
    isMenuOpen: boolean = false;
    constructor(
        private _eventService: EventBusService
    ){

    }

    ngOnInit(): void {
        this._eventService.on("navbar").subscribe((data)=>{
            console.log("data in navbar", data)
        })
    }

    clicked(){
        this.isMenuOpen = !this.isMenuOpen;
        console.log("clicked", this.isMenuOpen);
        if(this.isMenuOpen){
            gsap.to("#menu", {
                y: 150,
                ease: "power3.inOut",
                duration: 0.5,
                opacity: 1
            })
        } else {
            gsap.to("#menu", {
                y: -150,
                ease: "power3.inOut",
                duration: 0.5,
                opacity: 0
            })
        }
    }

}